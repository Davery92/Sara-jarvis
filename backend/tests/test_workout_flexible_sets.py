"""Flexible performed-set tests (§11 "Set matrix" of the 2026-07-27 plan).

Same rules as `test_workout_command_service.py`: real PostgreSQL, because the
properties under test — partial unique indexes, `FOR UPDATE`, JSONB snapshots,
`COUNT(*) FILTER` — are the ones SQLite would fake.

    docker compose -f docker-compose.dev.yml exec -T backend \\
        pytest tests/test_workout_flexible_sets.py

The through-line of every test here is §4.4's counting rules:

  - an extra working set raises the live target and the workout total;
  - a drop-set series belongs to ONE working set;
  - drop and warm-up sets add volume but consume no prescribed slot;
  - a voided set counts toward nothing — progress, volume, PRs, progression;
  - edits recompute derived values rather than incrementally guessing.
"""

import json
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the PostgreSQL dev database (run inside the backend container)"
)


TEMPLATE_EXERCISES = [
    {"name": "Bench Press", "sets": 2, "reps": "8-10", "rpe_target": 8, "rest_seconds": 120},
    {"name": "Barbell Row", "sets": 2, "reps": "8-10", "rpe_target": 8, "rest_seconds": 120},
]


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')
    """), {"id": uid, "email": f"flexsets-{uid}@example.invalid"})
    pg.commit()
    yield uid
    for stmt in (
        "DELETE FROM workout_log WHERE user_id = :uid",
        "DELETE FROM exercise_pr WHERE user_id = :uid",
        "DELETE FROM workout_session_event WHERE user_id = :uid",
        "DELETE FROM workout_session_command WHERE user_id = :uid",
        "DELETE FROM workout_adjustment_proposal WHERE user_id = :uid",
        "DELETE FROM workout_approved_policy WHERE user_id = :uid",
        "DELETE FROM active_workout_session WHERE user_id = :uid",
        "DELETE FROM workout WHERE user_id = :uid",
        "DELETE FROM fitness_template WHERE user_id = :uid",
        "DELETE FROM app_user WHERE id = :uid",
    ):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


@pytest.fixture
def svc():
    from app.services.workout_command_service import workout_command_service
    return workout_command_service


def _template(pg, user_id, name="Upper A", exercises=None):
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, :name, CAST(:ex AS jsonb))
    """), {"id": tid, "uid": user_id, "name": name,
           "ex": json.dumps(exercises or TEMPLATE_EXERCISES)})
    pg.commit()
    return tid


def _envelope(kind, session_id=None, version=None, payload=None, device="phone"):
    return {
        "schema_version": 1,
        "command_id": str(uuid.uuid4()),
        "session_id": session_id,
        "expected_version": version,
        "origin_device": device,
        "kind": kind,
        "payload": payload or {},
    }


class Runner:
    """Tracks the session version so tests read like a sequence of taps."""

    def __init__(self, svc, pg, user_id, session_id, version):
        self.svc, self.pg, self.user_id = svc, pg, user_id
        self.session_id, self.version = session_id, version

    async def __call__(self, kind, payload=None, device="phone", command_id=None):
        env = _envelope(kind, self.session_id, self.version, payload, device)
        if command_id:
            env["command_id"] = command_id
        result = await self.svc.execute(self.pg, self.user_id, env)
        if result.get("projection"):
            self.version = result["projection"]["version"]
        return result

    def projection(self):
        return self.svc.sync(self.pg, self.user_id)["projection"]


async def _started(svc, pg, user_id, exercises=None):
    tid = _template(pg, user_id, exercises=exercises)
    start = await svc.start(pg, user_id, tid)
    proj = start["projection"]
    return Runner(svc, pg, user_id, proj["session_id"], proj["version"])


# ────────────────────────────────────────────────────────────────────────
# Add set
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_add_set_raises_target_and_total_without_touching_the_template(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    template_id = pg.execute(text(
        "SELECT template_id FROM active_workout_session WHERE id = :s"
    ), {"s": run.session_id}).scalar()
    before = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :t"
    ), {"t": template_id}).scalar()

    result = await run("add_set", {"exercise_index": 0})

    assert result["target_sets"] == 3
    assert result["prescribed_sets"] == 2
    proj = result["projection"]
    assert proj["exercises"][0]["target_sets"] == 3
    assert proj["exercises"][0]["prescribed_sets"] == 2
    # Workout total moves with the effective target (§6.2).
    assert proj["progress"]["total_sets"] == 5

    after = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :t"
    ), {"t": template_id}).scalar()
    # §4.3 — the live snapshot changed, the program did not.
    assert after == before


@requires_pg
@pytest.mark.asyncio
async def test_add_set_after_the_exercise_finished_reopens_it(pg, svc, user_id):
    """§11 set matrix: 'add a set after the exercise originally completed'."""
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8})
    result = await run("log_set", {"weight": 135, "reps": 8})
    # Two of two done, so the cursor has moved on to the second exercise.
    assert result["projection"]["cursor"]["exercise_index"] == 1

    added = await run("add_set", {"exercise_index": 0})
    assert added["cursor_exercise_index"] == 0
    assert added["projection"]["cursor"]["set_index"] == 2
    assert added["projection"]["current_exercise"]["name"] == "Bench Press"


@requires_pg
@pytest.mark.asyncio
async def test_add_set_after_a_named_set_ignores_the_moved_cursor(pg, svc, user_id):
    """The Watch's rest-screen '+ Set' means one more of what was just done."""
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8})
    last = await run("log_set", {"weight": 135, "reps": 8})
    assert last["projection"]["cursor"]["exercise_index"] == 1  # moved on

    added = await run("add_set", {"after_set_id": last["logged"]["id"]}, device="watch")
    assert added["exercise_index"] == 0
    proj = run.projection()
    assert proj["exercises"][0]["target_sets"] == 3
    assert proj["exercises"][1]["target_sets"] == 2


@requires_pg
@pytest.mark.asyncio
async def test_duplicate_add_set_command_increments_once(pg, svc, user_id):
    """§12.8 — a retried Add Set must not add two sets."""
    run = await _started(svc, pg, user_id)
    cid = str(uuid.uuid4())
    first = await run("add_set", {"exercise_index": 0}, command_id=cid)
    replay = await svc.execute(pg, user_id, {
        **_envelope("add_set", run.session_id, first["projection"]["version"] - 1,
                    {"exercise_index": 0}),
        "command_id": cid,
    })
    assert replay["status"] == "replayed"
    assert run.projection()["exercises"][0]["target_sets"] == 3


@requires_pg
@pytest.mark.asyncio
async def test_remove_unlogged_set_refuses_to_delete_performed_work(pg, svc, user_id):
    from app.services.workout_command_service import WorkoutConflict

    run = await _started(svc, pg, user_id)
    await run("add_set", {"exercise_index": 0})
    await run("log_set", {"weight": 135, "reps": 8})
    await run("log_set", {"weight": 135, "reps": 8})
    await run("log_set", {"weight": 135, "reps": 8})

    # All three targets are now logged: there is no unlogged set to give back,
    # and removing one would have to erase real work.
    with pytest.raises(WorkoutConflict) as excinfo:
        await run("remove_unlogged_set", {"exercise_index": 0})
    assert excinfo.value.code == "target_floor"
    assert run.projection()["exercises"][0]["completed_sets"] == 3


@requires_pg
@pytest.mark.asyncio
async def test_remove_unlogged_set_will_not_go_below_the_prescription(pg, svc, user_id):
    """Shrinking the plan is a programming change, not an in-session tweak."""
    from app.services.workout_command_service import WorkoutConflict

    run = await _started(svc, pg, user_id)
    await run("add_set", {"exercise_index": 0})
    removed = await run("remove_unlogged_set", {"exercise_index": 0})
    assert removed["target_sets"] == 2

    with pytest.raises(WorkoutConflict):
        await run("remove_unlogged_set", {"exercise_index": 0})

    # ...unless it is asked for explicitly.
    explicit = await run("remove_unlogged_set", {"exercise_index": 0, "below_prescribed": True})
    assert explicit["target_sets"] == 1


# ────────────────────────────────────────────────────────────────────────
# Drop sets
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_three_segment_drop_set_counts_as_one_working_set(pg, svc, user_id):
    """§12.6 — each weight/reps pair preserved, one set of progress."""
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 135, "reps": 8})
    parent = logged["logged"]["id"]

    for weight, reps in ((115, 6), (95, 5), (75, 4)):
        segment = await run("log_drop_segment", {"weight": weight, "reps": reps})
        assert segment["logged"]["parent_set_id"] == parent
        assert segment["logged"]["set_kind"] == "drop"
        # A drop set is one continuous effort: no rest between segments.
        assert segment["rest_seconds"] == 0

    proj = run.projection()
    bench = proj["exercises"][0]
    assert bench["completed_sets"] == 1
    assert bench["completed_drop_segments"] == 3
    assert proj["progress"]["completed_sets"] == 1
    # Volume includes every segment: 135*8 + 115*6 + 95*5 + 75*4 = 2545
    assert proj["progress"]["total_volume"] == pytest.approx(2545)

    segments = pg.execute(text("""
        SELECT weight, reps, group_sequence FROM workout_log
        WHERE active_session_id = :s AND set_kind = 'drop'
        ORDER BY group_sequence
    """), {"s": run.session_id}).fetchall()
    assert [(int(r.weight), r.reps, r.group_sequence) for r in segments] == [
        (115, 6, 1), (95, 5, 2), (75, 4, 3),
    ]


@requires_pg
@pytest.mark.asyncio
async def test_drop_segment_without_a_working_set_is_refused(pg, svc, user_id):
    from app.services.workout_command_service import WorkoutConflict

    run = await _started(svc, pg, user_id)
    with pytest.raises(WorkoutConflict) as excinfo:
        await run("log_drop_segment", {"weight": 95, "reps": 6})
    assert excinfo.value.code == "no_parent_set"


@requires_pg
@pytest.mark.asyncio
async def test_drop_segment_after_an_extra_set_attaches_to_it(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    await run("add_set", {"exercise_index": 0})
    await run("log_set", {"weight": 135, "reps": 8})
    await run("log_set", {"weight": 135, "reps": 8})
    third = await run("log_set", {"weight": 135, "reps": 7})

    segment = await run("log_drop_segment", {"weight": 95, "reps": 6})
    assert segment["logged"]["parent_set_id"] == third["logged"]["id"]
    assert run.projection()["exercises"][0]["completed_sets"] == 3


@requires_pg
@pytest.mark.asyncio
async def test_drop_segments_do_not_feed_progression(pg, svc, user_id):
    """§8 — a deliberately lighter segment must not read as a regression."""
    from app.services.progressive_overload import fetch_last_session

    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8})
    await run("log_drop_segment", {"weight": 75, "reps": 12})
    pg.commit()

    last = fetch_last_session(pg, user_id, "Bench Press")
    assert last["weights"] == [135.0]


# ────────────────────────────────────────────────────────────────────────
# Warm-ups
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_warmup_adds_volume_but_no_progress_and_no_pr(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 45, "reps": 10, "set_kind": "warmup"})

    proj = run.projection()
    assert proj["progress"]["completed_sets"] == 0
    assert proj["exercises"][0]["completed_sets"] == 0
    assert proj["progress"]["total_volume"] == pytest.approx(450)

    prs = pg.execute(text(
        "SELECT COUNT(*) FROM exercise_pr WHERE user_id = :u"
    ), {"u": user_id}).scalar()
    assert prs == 0


# ────────────────────────────────────────────────────────────────────────
# Undo / revise
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_void_set_removes_it_from_progress_volume_and_prs(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 225, "reps": 5})
    set_id = logged["logged"]["id"]
    assert pg.execute(text(
        "SELECT COUNT(*) FROM exercise_pr WHERE workout_set_id = :s"
    ), {"s": set_id}).scalar() == 1

    voided = await run("void_set", {"set_id": set_id, "reason": "wrong bar"})
    assert voided["voided"]["id"] == set_id

    proj = run.projection()
    assert proj["progress"]["completed_sets"] == 0
    assert proj["progress"]["total_volume"] == pytest.approx(0)
    assert proj["exercises"][0]["completed_sets"] == 0
    # The PR it produced is withdrawn — Sara must not congratulate a lift that
    # David has just said did not happen (§12.7).
    assert pg.execute(text(
        "SELECT COUNT(*) FROM exercise_pr WHERE workout_set_id = :s"
    ), {"s": set_id}).scalar() == 0
    # The row survives, struck: "this didn't happen" is auditable information.
    row = pg.execute(text(
        "SELECT voided_at, void_reason, counts_toward_target FROM workout_log WHERE id = :s"
    ), {"s": set_id}).fetchone()
    assert row.voided_at is not None
    assert row.void_reason == "wrong bar"
    assert row.counts_toward_target is False


@requires_pg
@pytest.mark.asyncio
async def test_void_without_a_set_id_undoes_the_last_one(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8})
    second = await run("log_set", {"weight": 140, "reps": 8})

    voided = await run("void_set", {})
    assert voided["voided"]["id"] == second["logged"]["id"]
    assert run.projection()["progress"]["completed_sets"] == 1


@requires_pg
@pytest.mark.asyncio
async def test_voiding_a_working_set_takes_its_drop_segments_with_it(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 135, "reps": 8})
    await run("log_drop_segment", {"weight": 95, "reps": 6})
    await run("log_drop_segment", {"weight": 75, "reps": 5})

    voided = await run("void_set", {"set_id": logged["logged"]["id"]})
    assert voided["voided"]["drop_segments_voided"] == 2
    assert run.projection()["progress"]["total_volume"] == pytest.approx(0)


@requires_pg
@pytest.mark.asyncio
async def test_void_is_idempotent(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 135, "reps": 8})
    await run("void_set", {"set_id": logged["logged"]["id"]})
    again = await run("void_set", {"set_id": logged["logged"]["id"]})
    assert again["voided"]["already"] is True


@requires_pg
@pytest.mark.asyncio
async def test_revise_recomputes_volume_and_withdraws_the_old_pr(pg, svc, user_id):
    """§12.7 — correcting a mistaken PR must not leave the record standing."""
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 315, "reps": 5})
    set_id = logged["logged"]["id"]
    assert pg.execute(text(
        "SELECT COUNT(*) FROM exercise_pr WHERE workout_set_id = :s"
    ), {"s": set_id}).scalar() == 1

    revised = await run("revise_set", {"set_id": set_id, "weight": 135, "reps": 5})
    assert revised["revised"]["weight"] == 135

    proj = run.projection()
    assert proj["progress"]["total_volume"] == pytest.approx(675)
    prs = pg.execute(text(
        "SELECT weight FROM exercise_pr WHERE user_id = :u ORDER BY achieved_at"
    ), {"u": user_id}).fetchall()
    # Exactly one record, for the corrected weight — not one of each.
    assert [int(r.weight) for r in prs] == [135]


@requires_pg
@pytest.mark.asyncio
async def test_revise_to_warmup_gives_back_the_set_slot(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    logged = await run("log_set", {"weight": 45, "reps": 12})
    assert run.projection()["exercises"][0]["completed_sets"] == 1

    await run("revise_set", {"set_id": logged["logged"]["id"], "set_kind": "warmup"})
    proj = run.projection()
    assert proj["exercises"][0]["completed_sets"] == 0
    # Volume stays: the reps were performed either way.
    assert proj["progress"]["total_volume"] == pytest.approx(540)


@requires_pg
@pytest.mark.asyncio
async def test_a_set_from_another_session_cannot_be_touched(pg, svc, user_id):
    from app.services.workout_command_service import WorkoutConflict

    run = await _started(svc, pg, user_id)
    with pytest.raises(WorkoutConflict) as excinfo:
        await run("void_set", {"set_id": str(uuid.uuid4())})
    assert excinfo.value.code == "set_not_found"


# ────────────────────────────────────────────────────────────────────────
# Cross-device (§11 "add on Watch and log it on phone")
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_set_added_on_watch_is_immediately_loggable_from_the_phone(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8}, device="phone")
    await run("log_set", {"weight": 135, "reps": 8}, device="phone")
    await run("add_set", {"exercise_index": 0}, device="watch")

    result = await run("log_set", {"weight": 135, "reps": 6, "exercise_index": 0}, device="phone")
    assert result["logged"]["set_number"] == 3
    proj = run.projection()
    assert proj["exercises"][0]["completed_sets"] == 3
    assert proj["progress"]["completed_sets"] == 3


# ────────────────────────────────────────────────────────────────────────
# Approval boundary (§11 "Approval matrix")
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_sara_cannot_add_a_set_without_approval(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    proposal = svc.propose_extra_work(
        pg, user_id, run.session_id,
        kind="add_working_set", exercise_index=0,
        reason="That last set moved fast — one more?",
    )
    pg.commit()

    # Pending changes nothing.
    assert run.projection()["exercises"][0]["target_sets"] == 2

    approved = await run("approve_proposal", {"proposal_id": proposal["proposal_id"]})
    assert approved["applied"] is True
    assert run.projection()["exercises"][0]["target_sets"] == 3


@requires_pg
@pytest.mark.asyncio
async def test_rejecting_an_extra_set_proposal_changes_nothing(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    proposal = svc.propose_extra_work(
        pg, user_id, run.session_id,
        kind="add_working_set", exercise_index=0, reason="One more?",
    )
    pg.commit()

    rejected = await run("reject_proposal", {"proposal_id": proposal["proposal_id"]})
    assert rejected["applied"] is False
    assert run.projection()["exercises"][0]["target_sets"] == 2


@requires_pg
@pytest.mark.asyncio
async def test_approving_a_proposal_twice_applies_once(pg, svc, user_id):
    run = await _started(svc, pg, user_id)
    proposal = svc.propose_extra_work(
        pg, user_id, run.session_id,
        kind="add_working_set", exercise_index=0, reason="One more?",
    )
    pg.commit()

    await run("approve_proposal", {"proposal_id": proposal["proposal_id"]})
    second = await run("approve_proposal", {"proposal_id": proposal["proposal_id"]})
    assert second["applied"] is False
    assert run.projection()["exercises"][0]["target_sets"] == 3


@requires_pg
@pytest.mark.asyncio
async def test_adding_a_set_never_edits_the_template_without_a_second_approval(pg, svc, user_id):
    """§4.3 / §12.9 — the in-session tap changes today. The plan needs its own yes."""
    from app.core.feature_flags import Flag

    run = await _started(svc, pg, user_id)
    template_id = pg.execute(text(
        "SELECT template_id FROM active_workout_session WHERE id = :s"
    ), {"s": run.session_id}).scalar()

    await run("add_set", {"exercise_index": 0})
    for _ in range(3):
        await run("log_set", {"weight": 135, "reps": 8, "exercise_index": 0})
    for _ in range(2):
        await run("log_set", {"weight": 95, "reps": 8, "exercise_index": 1})

    # The post-workout question only exists behind the v2 flag, same as every
    # other proposal this service raises.
    import app.services.workout_command_service as mod
    original = mod._v2_enabled
    mod._v2_enabled = lambda: True
    try:
        await run("complete", {})
    finally:
        mod._v2_enabled = original
    pg.commit()

    def template_sets():
        raw = pg.execute(text(
            "SELECT exercises FROM fitness_template WHERE id = :t"
        ), {"t": template_id}).scalar()
        specs = json.loads(raw) if isinstance(raw, str) else raw
        return next(s["sets"] for s in specs if s["name"] == "Bench Press")

    # Workout over, template untouched.
    assert template_sets() == 2

    proposal = next(
        p for p in svc.list_proposals(pg, user_id, status="pending")
        if p["kind"] == "template_set_count"
    )
    assert proposal["proposed_value"]["sets"] == 3

    await svc.execute(pg, user_id, _envelope(
        "approve_proposal", None, None, {"proposal_id": proposal["proposal_id"]}
    ))
    pg.commit()
    assert template_sets() == 3


@requires_pg
@pytest.mark.asyncio
async def test_drop_set_proposal_does_not_log_anything_on_approval(pg, svc, user_id):
    """Sara cannot perform a set. Approval arms the entry screen (§4.2)."""
    run = await _started(svc, pg, user_id)
    await run("log_set", {"weight": 135, "reps": 8})
    proposal = svc.propose_extra_work(
        pg, user_id, run.session_id,
        kind="perform_drop_set", exercise_index=0, reason="Finish with a drop?",
    )
    pg.commit()

    before = run.projection()["progress"]["total_volume"]
    await run("approve_proposal", {"proposal_id": proposal["proposal_id"]})
    assert run.projection()["progress"]["total_volume"] == pytest.approx(before)
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s AND set_kind = 'drop'"
    ), {"s": run.session_id}).scalar() == 0
