"""Step 16 of FITNESS_COACH_IMPLEMENTATION_PLAN: PR records survive
corrections, and a retraction cannot leave a false claim or no claim.

A PR is the number an athlete cares most about, and both ways of getting it
wrong are silent:

* **A record standing on a set that was voided** congratulates someone for a
  lift they said did not happen.
* **No record at all after a retraction**, when an eligible set remains, is
  strictly worse than the stale answer — the athlete's actual best
  disappears.

These run against PostgreSQL because the withdrawal columns, the partial
index that excludes withdrawn rows, and the interaction with the command
service's transaction ordering are all PostgreSQL facts.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_prs_pg.py
"""
import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)


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
def athlete(pg):
    uid = f"pr-{uuid.uuid4().hex[:20]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW())
    """), {"id": uid, "e": f"{uid}@pr.invalid", "p": "$2b$12$" + "x" * 53})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("exercise_pr", "workout_log", "workout",
                  "active_workout_session", "workout_session_command",
                  "fitness_exercise_performance", "fitness_template"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


@pytest.fixture
def svc(monkeypatch):
    from app.services.workout_command_service import workout_command_service
    from app.celery_app import celery_app
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    return workout_command_service


class _Runner:
    def __init__(self, svc, pg, user_id, session_id, version):
        self.svc, self.pg, self.user_id = svc, pg, user_id
        self.session_id, self.version = session_id, version

    async def __call__(self, kind, payload=None):
        result = await self.svc.execute(self.pg, self.user_id, {
            "schema_version": 1,
            "command_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "expected_version": self.version,
            "origin_device": "web",
            "kind": kind,
            "payload": payload or {},
        })
        if result.get("projection"):
            self.version = result["projection"]["version"]
        return result


async def _start(svc, pg, user_id, *, sets=6):
    import json
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, 'PR fixture', CAST(:ex AS jsonb))
    """), {"id": tid, "uid": user_id, "ex": json.dumps([
        {"name": "Bench Press", "sets": sets, "reps": 5},
    ])})
    pg.commit()
    start = await svc.start(pg, user_id, tid)
    projection = start["projection"]
    return _Runner(svc, pg, user_id, projection["session_id"],
                   projection["version"])


def _live_prs(pg, user_id):
    return pg.execute(text("""
        SELECT weight, reps, estimated_1rm, pr_kind, formula_version
        FROM exercise_pr
        WHERE user_id = :u AND withdrawn_at IS NULL
        ORDER BY estimated_1rm DESC
    """), {"u": user_id}).fetchall()


def _withdrawn_prs(pg, user_id):
    return pg.execute(text("""
        SELECT weight, withdrawn_reason FROM exercise_pr
        WHERE user_id = :u AND withdrawn_at IS NOT NULL
    """), {"u": user_id}).fetchall()


# ── Schema ────────────────────────────────────────────────────────────────

@requires_pg
def test_the_withdrawal_columns_and_index_exist(pg):
    """The retraction has to be expressible, and the live-PR read has to be
    an index scan rather than a filter over the athlete's whole history."""
    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'exercise_pr'
    """)).fetchall()}
    assert {"withdrawn_at", "withdrawn_reason", "pr_kind",
            "formula_version", "exercise_library_id", "load_unit"} <= columns

    definition = pg.execute(text("""
        SELECT indexdef FROM pg_indexes
        WHERE tablename = 'exercise_pr' AND indexname = 'ix_exercise_pr_canonical'
    """)).scalar()
    assert definition is not None
    assert "withdrawn_at IS NULL" in definition, (
        "the index must exclude withdrawn rows, which is the read every "
        "consumer actually makes"
    )


# ── Recording ─────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_a_pr_records_its_formula_version_and_kind(pg, svc, athlete):
    """So a later change to the e1RM formula cannot silently reinterpret an
    old record as a different number."""
    run = await _start(svc, pg, athlete)
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})

    prs = _live_prs(pg, athlete)
    assert len(prs) == 1
    assert prs[0].pr_kind == "estimated_1rm"
    # Brzycki, which is what `calculate_estimated_1rm` actually computes.
    # Labelling it `epley_v1` would be worse than labelling nothing: a stored
    # formula version is only useful if it names the formula that was
    # applied. (The analytics module uses Epley per the plan's §9.5; the two
    # deliberately differ until Step 18 reconciles them, because changing the
    # ledger's formula would re-rank every record an athlete already has.)
    assert prs[0].formula_version == "brzycki_v1"
    assert float(prs[0].estimated_1rm) == pytest.approx(
        225 * 36 / (37 - 5), abs=0.01
    )


@requires_pg
@pytest.mark.asyncio
async def test_the_ledger_and_the_analytics_formulas_are_both_declared(
    pg, svc, athlete,
):
    """They differ, and a stored version is what makes that recoverable.

    `calculate_estimated_1rm` is Brzycki and has been since before this
    work; `analytics.epley_1rm` is Epley, which the plan specifies. Changing
    the ledger would retroactively re-rank an athlete's records, so the two
    coexist with their versions recorded rather than one silently winning.
    """
    from app.routes.fitness import calculate_estimated_1rm
    from app.services.fitness.analytics import EPLEY_FORMULA_VERSION, epley_1rm

    brzycki = calculate_estimated_1rm(225, 5)
    epley = epley_1rm(225.0, 5)
    assert brzycki == pytest.approx(225 * 36 / (37 - 5), abs=0.01)
    assert epley == pytest.approx(225 * (1 + 5 / 30))
    assert brzycki != pytest.approx(epley), (
        "the two formulas genuinely differ, which is why each records its "
        "version rather than a bare number"
    )
    assert EPLEY_FORMULA_VERSION == "epley_v1"

    run = await _start(svc, pg, athlete)
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    assert _live_prs(pg, athlete)[0].formula_version == "brzycki_v1"


@requires_pg
@pytest.mark.asyncio
async def test_a_heavier_set_supersedes_the_lighter_record(pg, svc, athlete):
    run = await _start(svc, pg, athlete)
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    await run("log_set", {"exercise_index": 0, "weight": 245, "reps": 5})

    prs = _live_prs(pg, athlete)
    assert [int(p.weight) for p in prs] == [245, 225], (
        "both claims are recorded; the comparison is on estimated_1rm"
    )
    assert float(prs[0].estimated_1rm) > float(prs[1].estimated_1rm)


@requires_pg
@pytest.mark.asyncio
async def test_matching_a_record_is_not_breaking_it(pg, svc, athlete):
    """A tie is not a PR.

    This caught a real bug. `estimated_1rm` is a Python float and the stored
    best comes back as a Decimal; Python compares the two exactly, and the
    float nearest 253.12 is 253.1200000000000045…, strictly greater than
    Decimal('253.12'). So repeating a lift at the same weight and reps
    registered as a new PR every single time — the record was "broken" by
    matching it.
    """
    run = await _start(svc, pg, athlete)
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})

    assert len(_live_prs(pg, athlete)) == 1


@requires_pg
@pytest.mark.asyncio
async def test_a_warmup_does_not_claim_a_pr(pg, svc, athlete):
    run = await _start(svc, pg, athlete)
    await run("log_set", {
        "exercise_index": 0, "weight": 135, "reps": 10, "set_kind": "warmup",
    })
    assert _live_prs(pg, athlete) == []


@requires_pg
@pytest.mark.asyncio
async def test_a_drop_segment_does_not_claim_a_pr(pg, svc, athlete):
    """A drop segment is submaximal by design."""
    run = await _start(svc, pg, athlete)
    await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    before = len(_live_prs(pg, athlete))
    await run("log_drop_segment", {"exercise_index": 0, "weight": 185, "reps": 8})
    assert len(_live_prs(pg, athlete)) == before


# ── Retraction ────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_voiding_a_set_retracts_its_claim_and_keeps_the_reason(
    pg, svc, athlete,
):
    """"Why did my bench PR change?" has to be answerable.

    A hard DELETE leaves the athlete looking at a number that silently
    moved.
    """
    run = await _start(svc, pg, athlete)
    logged = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})
    assert len(_live_prs(pg, athlete)) == 1

    await run("void_set", {"set_id": logged["logged"]["id"], "reason": "wrong bar"})

    assert _live_prs(pg, athlete) == []
    withdrawn = _withdrawn_prs(pg, athlete)
    assert len(withdrawn) == 1
    assert int(withdrawn[0].weight) == 315
    assert withdrawn[0].withdrawn_reason


@requires_pg
@pytest.mark.asyncio
async def test_a_retraction_promotes_the_next_eligible_set(pg, svc, athlete):
    """Retracting without promoting leaves no record for a lift that has a
    best — strictly worse than the stale answer."""
    run = await _start(svc, pg, athlete)
    lighter = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    heavier = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})

    await run("void_set", {"set_id": heavier["logged"]["id"], "reason": "wrong bar"})

    assert pg.execute(text(
        "SELECT is_pr FROM workout_log WHERE id = :id"),
        {"id": lighter["logged"]["id"]}).scalar() is True


@requires_pg
@pytest.mark.asyncio
async def test_a_voided_set_is_never_promoted(pg, svc, athlete):
    """A voided set cannot hold a record — that is why the claim went.

    This is also the ordering trap: `_apply_void_set` retracts BEFORE it
    stamps `voided_at`, so a naive promotion query would see the set as
    still live and promote it straight back.
    """
    run = await _start(svc, pg, athlete)
    first = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    second = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})
    await run("void_set", {"set_id": first["logged"]["id"], "reason": "miscounted"})
    await run("void_set", {"set_id": second["logged"]["id"], "reason": "wrong bar"})

    flagged = pg.execute(text("""
        SELECT id FROM workout_log
        WHERE user_id = :u AND is_pr = true AND voided_at IS NOT NULL
    """), {"u": athlete}).fetchall()
    assert flagged == [], "a voided set must never carry the record flag"


@requires_pg
@pytest.mark.asyncio
async def test_a_correction_down_leaves_the_corrected_value_as_the_record(
    pg, svc, athlete,
):
    """The case that broke when withdrawal became soft.

    With the retracted 315 still in the table, the comparison had to learn to
    exclude it — otherwise correcting 315 down to 135 leaves the athlete with
    no record at all.
    """
    run = await _start(svc, pg, athlete)
    logged = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})
    await run("revise_set", {
        "set_id": logged["logged"]["id"], "weight": 135, "reps": 5,
    })

    live = _live_prs(pg, athlete)
    assert [int(p.weight) for p in live] == [135]
    assert [int(p.weight) for p in _withdrawn_prs(pg, athlete)] == [315]


@requires_pg
@pytest.mark.asyncio
async def test_a_correction_up_records_the_new_claim(pg, svc, athlete):
    run = await _start(svc, pg, athlete)
    logged = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    await run("revise_set", {
        "set_id": logged["logged"]["id"], "weight": 315, "reps": 5,
    })
    live = _live_prs(pg, athlete)
    assert [int(p.weight) for p in live] == [315]


@requires_pg
@pytest.mark.asyncio
async def test_voiding_a_working_set_retracts_its_drop_segments_claims_too(
    pg, svc, athlete,
):
    """The segments were performed as part of that set.

    Leaving them would attribute real work to a set the athlete said did not
    happen.
    """
    run = await _start(svc, pg, athlete)
    parent = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})
    await run("log_drop_segment", {"exercise_index": 0, "weight": 225, "reps": 5})

    await run("void_set", {"set_id": parent["logged"]["id"], "reason": "wrong bar"})

    remaining = pg.execute(text("""
        SELECT COUNT(*) FROM workout_log
        WHERE user_id = :u AND voided_at IS NULL
    """), {"u": athlete}).scalar()
    assert remaining == 0, "the drop segment went with its parent"
    assert _live_prs(pg, athlete) == []


# ── Isolation ─────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_a_retraction_does_not_touch_another_athletes_record(
    pg, svc, athlete,
):
    other = f"pr-other-{uuid.uuid4().hex[:12]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW())
    """), {"id": other, "e": f"{other}@pr.invalid", "p": "$2b$12$" + "x" * 53})
    pg.commit()
    try:
        others_run = await _start(svc, pg, other)
        await others_run("log_set", {"exercise_index": 0, "weight": 405, "reps": 5})
        assert len(_live_prs(pg, other)) == 1

        run = await _start(svc, pg, athlete)
        logged = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
        await run("void_set", {"set_id": logged["logged"]["id"], "reason": "x"})

        assert len(_live_prs(pg, other)) == 1, (
            "one athlete's void must not retract another's record"
        )
        assert _live_prs(pg, athlete) == []
    finally:
        pg.rollback()
        for table in ("exercise_pr", "workout_log", "workout",
                      "active_workout_session", "workout_session_command",
                      "fitness_exercise_performance", "fitness_template"):
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": other})
        pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": other})
        pg.commit()


@requires_pg
@pytest.mark.asyncio
async def test_promotion_only_considers_the_same_lift(pg, svc, athlete):
    """A squat cannot become the bench record."""
    import json
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, 'PR fixture', CAST(:ex AS jsonb))
    """), {"id": tid, "uid": athlete, "ex": json.dumps([
        {"name": "Bench Press", "sets": 3, "reps": 5},
        {"name": "Back Squat", "sets": 3, "reps": 5},
    ])})
    pg.commit()
    start = await svc.start(pg, athlete, tid)
    run = _Runner(svc, pg, athlete, start["projection"]["session_id"],
                  start["projection"]["version"])

    bench = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
    await run("log_set", {"exercise_index": 1, "weight": 405, "reps": 5})

    await run("void_set", {"set_id": bench["logged"]["id"], "reason": "wrong bar"})

    # The squat set keeps its own flag; nothing promoted it into the bench's
    # place, and the bench has no eligible set left.
    bench_flagged = pg.execute(text("""
        SELECT COUNT(*) FROM workout_log
        WHERE user_id = :u AND exercise_id = 'Bench Press'
          AND is_pr = true AND voided_at IS NULL
    """), {"u": athlete}).scalar()
    assert bench_flagged == 0
