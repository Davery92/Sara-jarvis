"""Cross-device workout command tests (§14.1 of the Apple Watch plan).

These run against a real PostgreSQL database, not the in-memory SQLite used by
the rest of the suite: the guarantees under test — `SELECT ... FOR UPDATE`,
JSONB snapshots, partial unique indexes, `ON CONFLICT DO NOTHING` on the
command log — are exactly the things SQLite would fake rather than enforce, so
a green SQLite run would prove nothing about the property that matters.

Run inside the backend container:

    docker compose exec -T backend pytest tests/test_workout_command_service.py

Everything is created under a throwaway user and torn down afterwards.
"""

import json
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    url = os.getenv("DATABASE_URL", "")
    return url.startswith("postgresql")


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
        INSERT INTO app_user (id, email, password_hash)
        VALUES (:id, :email, 'x')
    """), {"id": uid, "email": f"watch-test-{uid}@example.invalid"})
    pg.commit()
    yield uid
    # Children first — workout_log FKs workout, external_workout is standalone.
    for stmt in (
        "DELETE FROM workout_log WHERE user_id = :uid",
        "DELETE FROM exercise_pr WHERE user_id = :uid",
        "DELETE FROM workout_session_event WHERE user_id = :uid",
        "DELETE FROM workout_session_command WHERE user_id = :uid",
        "DELETE FROM workout_adjustment_proposal WHERE user_id = :uid",
        "DELETE FROM workout_approved_policy WHERE user_id = :uid",
        "DELETE FROM active_workout_session WHERE user_id = :uid",
        "DELETE FROM workout WHERE user_id = :uid",
        "DELETE FROM external_workout WHERE user_id = :uid",
        "DELETE FROM fitness_template WHERE user_id = :uid",
        "DELETE FROM app_user WHERE id = :uid",
    ):
        try:
            pg.execute(text(stmt), {"uid": uid})
            pg.commit()
        except Exception:
            pg.rollback()


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


@pytest.fixture
def svc():
    from app.services.workout_command_service import workout_command_service
    return workout_command_service


# ────────────────────────────────────────────────────────────────────────
# Start
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_first_start_creates_one_session(pg, svc, user_id):
    tid = _template(pg, user_id)
    result = await svc.start(pg, user_id, tid, origin_device="watch")

    assert result["status"] == "accepted"
    proj = result["projection"]
    assert proj["schema_version"] == 1
    assert proj["version"] == 1
    assert proj["origin_device"] == "watch"
    assert proj["progress"]["total_sets"] == 4
    assert proj["current_exercise"]["name"] == "Bench Press"

    count = pg.execute(text(
        "SELECT COUNT(*) FROM active_workout_session WHERE user_id = :u AND status='active'"
    ), {"u": user_id}).scalar()
    assert count == 1


@requires_pg
@pytest.mark.asyncio
async def test_duplicate_start_attempt_replays(pg, svc, user_id):
    """A Start retried through a dropped link must not create a second workout."""
    tid = _template(pg, user_id)
    attempt = str(uuid.uuid4())

    first = await svc.start(pg, user_id, tid, start_attempt_id=attempt, origin_device="watch")
    second = await svc.start(pg, user_id, tid, start_attempt_id=attempt, origin_device="watch")

    assert first["status"] == "accepted"
    assert second["status"] == "replayed"
    assert second["projection"]["session_id"] == first["projection"]["session_id"]
    assert pg.execute(text(
        "SELECT COUNT(*) FROM active_workout_session WHERE user_id = :u"
    ), {"u": user_id}).scalar() == 1


@requires_pg
@pytest.mark.asyncio
async def test_start_same_template_resumes(pg, svc, user_id):
    tid = _template(pg, user_id)
    first = await svc.start(pg, user_id, tid)
    again = await svc.start(pg, user_id, tid, origin_device="watch")

    assert again["status"] == "resumed"
    assert again["projection"]["session_id"] == first["projection"]["session_id"]


@requires_pg
@pytest.mark.asyncio
async def test_start_other_template_conflicts_without_abandoning(pg, svc, user_id):
    """§6.6 — a second controller must never wipe a running workout."""
    from app.services.workout_command_service import WorkoutConflict

    t1 = _template(pg, user_id, "Upper A")
    t2 = _template(pg, user_id, "Lower A")
    first = await svc.start(pg, user_id, t1)

    with pytest.raises(WorkoutConflict) as excinfo:
        await svc.start(pg, user_id, t2, origin_device="watch")

    assert excinfo.value.code == "active_workout_conflict"
    # The conflict carries the live projection so the Watch can offer Resume/End.
    assert excinfo.value.projection["session_id"] == first["projection"]["session_id"]

    still_active = pg.execute(text(
        "SELECT status FROM active_workout_session WHERE id = :s"
    ), {"s": first["projection"]["session_id"]}).scalar()
    assert still_active == "active"


@requires_pg
@pytest.mark.asyncio
async def test_start_with_abandon_policy_replaces(pg, svc, user_id):
    """Legacy phone behaviour stays available for rollback (§16.2)."""
    t1 = _template(pg, user_id, "Upper A")
    t2 = _template(pg, user_id, "Lower A")
    first = await svc.start(pg, user_id, t1)
    second = await svc.start(pg, user_id, t2, on_conflict="abandon")

    assert second["status"] == "accepted"
    assert second["projection"]["session_id"] != first["projection"]["session_id"]
    assert pg.execute(text(
        "SELECT status FROM active_workout_session WHERE id = :s"
    ), {"s": first["projection"]["session_id"]}).scalar() == "abandoned"


# ────────────────────────────────────────────────────────────────────────
# Log set — idempotency, versions, ordering
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_duplicate_log_set_command_cannot_duplicate_a_row(pg, svc, user_id):
    """The headline guarantee: double-tapping Log Set logs one set."""
    tid = _template(pg, user_id)
    start = await svc.start(pg, user_id, tid)
    sid = start["projection"]["session_id"]

    env = _envelope("log_set", sid, 1, {"weight": 135, "reps": 8, "effort": "right"}, "watch")
    first = await svc.execute(pg, user_id, env)
    replay = await svc.execute(pg, user_id, dict(env))

    assert first["status"] == "accepted"
    assert replay["status"] == "replayed"
    assert replay["logged"]["id"] == first["logged"]["id"]

    rows = pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar()
    assert rows == 1


@requires_pg
@pytest.mark.asyncio
async def test_stale_version_is_rejected(pg, svc, user_id):
    from app.services.workout_command_service import WorkoutConflict

    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    await svc.execute(pg, user_id, _envelope("log_set", sid, 1, {"weight": 135, "reps": 8}))

    # The Watch still believes it is on version 1.
    with pytest.raises(WorkoutConflict) as excinfo:
        await svc.execute(pg, user_id,
                          _envelope("log_set", sid, 1, {"weight": 135, "reps": 8}, "watch"))
    assert excinfo.value.code == "version_conflict"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar() == 1


@requires_pg
@pytest.mark.asyncio
async def test_command_for_a_different_session_is_rejected(pg, svc, user_id):
    from app.services.workout_command_service import WorkoutConflict

    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    with pytest.raises(WorkoutConflict) as excinfo:
        await svc.execute(pg, user_id, _envelope(
            "log_set", str(uuid.uuid4()), None, {"weight": 100, "reps": 5}, "watch"
        ))
    assert excinfo.value.code == "session_mismatch"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar() == 0


@requires_pg
@pytest.mark.asyncio
async def test_alternating_phone_and_watch_sets_converge(pg, svc, user_id):
    """§14.4 case 7 — sets logged from both devices land once, in order."""
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    version = 1
    for i, device in enumerate(["watch", "phone", "watch", "phone"]):
        res = await svc.execute(pg, user_id, _envelope(
            "log_set", sid, version, {"weight": 135 + i, "reps": 8}, device
        ))
        version = res["projection"]["version"]

    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar() == 4
    proj = svc.sync(pg, user_id)["projection"]
    assert proj["progress"]["completed_sets"] == 4
    # Two exercises × two sets = workout finished, cursor stays in range.
    assert proj["cursor"]["exercise_index"] in (0, 1)


@requires_pg
@pytest.mark.asyncio
async def test_exercise_jump_resumes_partial_progress(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    r = await svc.execute(pg, user_id, _envelope("log_set", sid, 1, {"weight": 135, "reps": 8}))
    v = r["projection"]["version"]
    r = await svc.execute(pg, user_id, _envelope("select_exercise", sid, v, {"exercise_index": 1}))
    assert r["projection"]["cursor"]["exercise_index"] == 1
    assert r["projection"]["cursor"]["set_index"] == 0

    v = r["projection"]["version"]
    r = await svc.execute(pg, user_id, _envelope("select_exercise", sid, v, {"exercise_index": 0}))
    # One set of Bench already done — returning resumes mid-exercise.
    assert r["projection"]["cursor"]["set_index"] == 1


@requires_pg
@pytest.mark.asyncio
async def test_variant_scopes_logging_to_the_machine_used(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    r = await svc.execute(pg, user_id, _envelope(
        "set_variant", sid, 1, {"exercise_index": 0, "variant": "Smith Machine Bench"}
    ))
    v = r["projection"]["version"]
    await svc.execute(pg, user_id, _envelope("log_set", sid, v, {"weight": 155, "reps": 8}))

    logged = pg.execute(text(
        "SELECT exercise_id, flags FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).fetchone()
    assert logged.exercise_id == "Smith Machine Bench"
    assert logged.flags["base_exercise"] == "Bench Press"


@requires_pg
@pytest.mark.asyncio
async def test_rest_start_and_stop_replay(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    env = _envelope("rest_start", sid, 1, {"duration_seconds": 90})
    first = await svc.execute(pg, user_id, env)
    replay = await svc.execute(pg, user_id, dict(env))
    assert first["duration_seconds"] == 90
    assert replay["status"] == "replayed"
    assert first["projection"]["rest"]["active"] is True

    v = first["projection"]["version"]
    stopped = await svc.execute(pg, user_id, _envelope("rest_stop", sid, v))
    assert stopped["projection"]["rest"]["active"] is False


@requires_pg
@pytest.mark.asyncio
async def test_rest_duration_is_clamped_to_the_approved_policy(pg, svc, user_id):
    """§6.9 — Sara operates inside the range, she does not widen it."""
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    await svc.execute(pg, user_id, _envelope(
        "set_policy", None, None, {"policy": {"rest_range_seconds": [60, 120]}}
    ))
    r = await svc.execute(pg, user_id, _envelope("rest_start", sid, 1, {"duration_seconds": 600}))
    assert r["duration_seconds"] == 120


@requires_pg
@pytest.mark.asyncio
async def test_set_policy_ignores_unknown_keys(pg, svc, user_id):
    r = await svc.execute(pg, user_id, _envelope(
        "set_policy", None, None,
        {"policy": {"speak_prs": True, "may_rewrite_program": True}},
    ))
    assert r["policy"]["speak_prs"] is True
    assert "may_rewrite_program" not in r["policy"]


# ────────────────────────────────────────────────────────────────────────
# Completion / abandonment / HealthKit link
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_complete_replay_is_idempotent(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    env = _envelope("complete", sid, 1, {}, "watch")
    first = await svc.execute(pg, user_id, env)
    replay = await svc.execute(pg, user_id, dict(env))

    assert first["summary"]["workout_name"] == "Upper A"
    assert replay["status"] == "replayed"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM active_workout_session WHERE user_id=:u AND status='completed'"
    ), {"u": user_id}).scalar() == 1


@requires_pg
@pytest.mark.asyncio
async def test_complete_links_the_exact_healthkit_workout(pg, svc, user_id):
    """§4.5 / §6.4 — one Sara workout, one HealthKit workout, bound by UUID."""
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    hk = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO external_workout (
            id, user_id, source, external_id, activity_type,
            started_at, ended_at, duration_seconds,
            total_energy_kcal, avg_heart_rate, max_heart_rate
        ) VALUES (
            :id, :uid, 'apple_health', :hk, '50',
            NOW() - INTERVAL '45 minutes', NOW(), 2700, 410, 128, 171
        )
    """), {"id": str(uuid.uuid4()), "uid": user_id, "hk": hk})
    pg.commit()

    res = await svc.execute(pg, user_id, _envelope(
        "complete", sid, 1, {"healthkit_workout_uuid": hk}, "watch"
    ))

    hr = res["summary"]["heart_rate"]
    assert hr["linked"] is True
    assert hr["avg_heart_rate"] == 128
    assert hr["max_heart_rate"] == 171
    assert pg.execute(text(
        "SELECT sara_session_id FROM external_workout WHERE external_id = :hk"
    ), {"hk": hk}).scalar() == sid
    assert pg.execute(text(
        "SELECT healthkit_workout_uuid FROM active_workout_session WHERE id = :s"
    ), {"s": sid}).scalar() == hk


@requires_pg
@pytest.mark.asyncio
async def test_healthkit_link_endpoint_is_idempotent(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    hk = str(uuid.uuid4())

    first = svc.link_healthkit(pg, user_id, sid, hk, activity_type="50")
    second = svc.link_healthkit(pg, user_id, sid, hk, activity_type="50")
    assert first["success"] and second["success"]
    assert pg.execute(text(
        "SELECT healthkit_state FROM active_workout_session WHERE id = :s"
    ), {"s": sid}).scalar() == "ended"


@requires_pg
@pytest.mark.asyncio
async def test_abandon_removes_sets_and_confirms_once(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    r = await svc.execute(pg, user_id, _envelope("log_set", sid, 1, {"weight": 135, "reps": 8}))

    env = _envelope("abandon", sid, r["projection"]["version"], {}, "phone")
    await svc.execute(pg, user_id, env)
    replay = await svc.execute(pg, user_id, dict(env))

    assert replay["status"] == "replayed"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar() == 0
    assert pg.execute(text(
        "SELECT status FROM active_workout_session WHERE id = :s"
    ), {"s": sid}).scalar() == "abandoned"


# ────────────────────────────────────────────────────────────────────────
# Approval boundary (§11)
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_hard_set_creates_a_proposal_but_changes_nothing(pg, svc, user_id):
    tid = _template(pg, user_id)
    start = await svc.start(pg, user_id, tid)
    sid = start["projection"]["session_id"]
    before = start["projection"]["exercises"][0]["approved_weight"]

    res = await svc.execute(pg, user_id, _envelope(
        "log_set", sid, 1, {"weight": 135, "reps": 8, "effort": "hard"}, "watch"
    ))

    proposal = res["proposal"]
    assert proposal is not None
    assert proposal["status"] == "pending"
    assert proposal["proposed_value"]["weight"] == 130.0
    # Recommendation only — the execution target is untouched.
    after = res["projection"]["exercises"][0]["approved_weight"]
    assert after == before


@requires_pg
@pytest.mark.asyncio
async def test_approving_a_proposal_applies_exactly_that_value(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    res = await svc.execute(pg, user_id, _envelope(
        "log_set", sid, 1, {"weight": 135, "reps": 8, "effort": "hard"}
    ))
    pid = res["proposal"]["proposal_id"]
    v = res["projection"]["version"]

    approved = await svc.execute(pg, user_id, _envelope(
        "approve_proposal", sid, v, {"proposal_id": pid}, "watch"
    ))

    assert approved["applied"] is True
    assert approved["projection"]["exercises"][0]["approved_weight"] == 130.0
    row = pg.execute(text(
        "SELECT status, resolved_by_device FROM workout_adjustment_proposal WHERE id = :p"
    ), {"p": pid}).fetchone()
    assert row.status == "approved"
    assert row.resolved_by_device == "watch"


@requires_pg
@pytest.mark.asyncio
async def test_rejecting_a_proposal_changes_nothing(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    res = await svc.execute(pg, user_id, _envelope(
        "log_set", sid, 1, {"weight": 135, "reps": 8, "effort": "hard"}
    ))
    pid = res["proposal"]["proposal_id"]
    before = res["projection"]["exercises"][0]["approved_weight"]

    rejected = await svc.execute(pg, user_id, _envelope(
        "reject_proposal", sid, res["projection"]["version"], {"proposal_id": pid}
    ))

    assert rejected["applied"] is False
    assert rejected["projection"]["exercises"][0]["approved_weight"] == before
    assert pg.execute(text(
        "SELECT status FROM workout_adjustment_proposal WHERE id = :p"
    ), {"p": pid}).scalar() == "rejected"


@requires_pg
@pytest.mark.asyncio
async def test_expired_proposal_cannot_be_applied(pg, svc, user_id):
    """Silence and expiry are not approval (§2.4)."""
    from app.services.workout_command_service import WorkoutConflict

    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    res = await svc.execute(pg, user_id, _envelope(
        "log_set", sid, 1, {"weight": 135, "reps": 8, "effort": "hard"}
    ))
    pid = res["proposal"]["proposal_id"]
    before = res["projection"]["exercises"][0]["approved_weight"]

    pg.execute(text(
        "UPDATE workout_adjustment_proposal SET expires_at = NOW() - INTERVAL '1 minute' WHERE id = :p"
    ), {"p": pid})
    pg.commit()

    with pytest.raises(WorkoutConflict) as excinfo:
        await svc.execute(pg, user_id, _envelope(
            "approve_proposal", sid, res["projection"]["version"], {"proposal_id": pid}
        ))
    assert excinfo.value.code == "proposal_stale"

    snap = pg.execute(text(
        "SELECT workout_snapshot FROM active_workout_session WHERE id = :s"
    ), {"s": sid}).scalar()
    assert snap["exercises"][0]["approved_weight"] == before


# ────────────────────────────────────────────────────────────────────────
# Coaching decoupling + sync + catalog
# ────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_coaching_failure_does_not_fail_log_set(pg, svc, user_id, monkeypatch):
    """§6.7 exit criterion — a dead LLM costs a sentence, not a set."""
    from app.services.workout_session_service import workout_session_service as legacy

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(legacy, "_generate_set_feedback", boom)

    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    res = await svc.execute(pg, user_id, _envelope("log_set", sid, 1, {"weight": 135, "reps": 8}))

    assert res["status"] == "accepted"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM workout_log WHERE active_session_id = :s"
    ), {"s": sid}).scalar() == 1


@requires_pg
@pytest.mark.asyncio
async def test_sync_returns_projection_and_unexpired_events(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]

    svc.record_event(pg, user_id, sid, kind="set_feedback", text_="Good set.",
                     after_version=1, speak=True)
    svc.record_event(pg, user_id, sid, kind="set_feedback", text_="Stale.",
                     after_version=1, ttl_seconds=-1)
    pg.commit()

    out = svc.sync(pg, user_id, after_version=0)
    assert out["projection"]["session_id"] == sid
    texts = [e["text"] for e in out["events"]]
    assert "Good set." in texts
    assert "Stale." not in texts


@requires_pg
@pytest.mark.asyncio
async def test_catalog_gives_the_watch_enough_to_start(pg, svc, user_id):
    _template(pg, user_id, "Upper A")
    cat = svc.catalog(pg, user_id)

    assert cat["schema_version"] == 1
    assert any(t["name"] == "Upper A" and t["exercise_count"] == 2 for t in cat["templates"])
    assert cat["active_projection"] is None
    assert "rest_range_seconds" in cat["policy"]


@requires_pg
@pytest.mark.asyncio
async def test_catalog_includes_a_compact_active_projection(pg, svc, user_id):
    tid = _template(pg, user_id)
    await svc.start(pg, user_id, tid)
    cat = svc.catalog(pg, user_id)

    active = cat["active_projection"]
    assert active is not None
    # Compact form: the Watch renders from current_exercise, not the full list.
    assert "exercises" not in active
    assert active["current_exercise"]["name"] == "Bench Press"


@requires_pg
@pytest.mark.asyncio
async def test_unknown_command_kind_is_refused(pg, svc, user_id):
    tid = _template(pg, user_id)
    sid = (await svc.start(pg, user_id, tid))["projection"]["session_id"]
    with pytest.raises(ValueError):
        await svc.execute(pg, user_id, _envelope("rewrite_program", sid, 1, {}))
