"""Step 13 of FITNESS_COACH_IMPLEMENTATION_PLAN: a session's work has a
stable shape, and precise loads and effort survive being stored.

The two defects, both of which produce plausible wrong numbers:

* **`workout_log.weight` is an INTEGER.** Every fractional load any client
  has ever logged was rounded. Three sessions at 227.5 lb read back as 227,
  227, 227 — which is indistinguishable from a plateau.
* **The same exercise twice in one session is one group of sets.** Sets are
  tagged with the session and a text name, so "bench, something else, bench
  again" has no way to say which block a set belonged to.

Everything here runs through `workout_command_service`, because that service
is the single mutation authority — it holds the session lock, enforces
`expected_version`, replays idempotently and owns void and correction.
Writing a set any other way would bypass all of it, so these tests drive
commands rather than SQL.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_performance_pg.py
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

UTC = timezone.utc


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
    unusable_hash = "$2b$12$" + "x" * 53
    uid = f"m7-{uuid.uuid4().hex[:20]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW())
    """), {"id": uid, "e": f"{uid}@m7.invalid", "p": unusable_hash})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("fitness_pain_report", "exercise_pr", "workout_log",
                  "fitness_exercise_performance", "workout_session",
                  "active_workout_session", "workout_session_command",
                  "workout", "fitness_template", "fitness_athlete_profile"):
        pg.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM fitness_exercise_alias WHERE owner_user_id = :u"),
               {"u": uid})
    pg.execute(text("DELETE FROM exercise_library WHERE name LIKE 'M7TEST %'"))
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


@pytest.fixture
def svc(monkeypatch):
    from app.services.workout_command_service import workout_command_service
    from app.celery_app import celery_app
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    return workout_command_service


class _Runner:
    """Tracks the session version so a test reads as a sequence of taps.

    Same shape as the helper in `test_workout_flexible_sets.py`: commands
    carry `expected_version`, which is what the service uses to refuse a
    stale write.
    """

    def __init__(self, svc, pg, user_id, session_id, version):
        self.svc, self.pg, self.user_id = svc, pg, user_id
        self.session_id, self.version = session_id, version

    async def __call__(self, kind, payload=None, *, command_id=None):
        envelope = {
            "schema_version": 1,
            "command_id": command_id or str(uuid.uuid4()),
            "session_id": self.session_id,
            "expected_version": self.version,
            "origin_device": "web",
            "kind": kind,
            "payload": payload or {},
        }
        result = await self.svc.execute(self.pg, self.user_id, envelope)
        if result.get("projection"):
            self.version = result["projection"]["version"]
        return result

    def projection(self):
        return self.svc.sync(self.pg, self.user_id)["projection"]


async def _start(svc, pg, user_id, exercises):
    """Start a real session through `svc.start`.

    Not hand-inserted: `start` creates the `workout` aggregate the
    `workout_log.workout_id` FK requires, writes the snapshot, and stamps the
    version — so a hand-built session would be missing the parent row and
    would not exercise the path a client actually takes.
    """
    import json
    tid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (id, user_id, name, exercises)
        VALUES (:id, :uid, 'M7 fixture template', CAST(:ex AS jsonb))
    """), {"id": tid, "uid": user_id, "ex": json.dumps(exercises)})
    pg.commit()
    start = await svc.start(pg, user_id, tid)
    projection = start["projection"]
    return _Runner(svc, pg, user_id, projection["session_id"], projection["version"])


def _exercise_row(pg, name, *, convention="total"):
    from app.schemas.fitness_coach import normalize_code
    eid = str(uuid.uuid4())
    norm = normalize_code(name)
    pg.execute(text("""
        INSERT INTO exercise_library
            (id, name, normalized_name, movement_pattern, load_convention,
             created_at, updated_at)
        VALUES (:id, :name, :norm, 'push', :conv, NOW(), NOW())
    """), {"id": eid, "name": name, "norm": norm, "conv": convention})
    pg.execute(text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, locale, review_status, source, reviewed_at)
        VALUES (:aid, :norm, :name, :eid, NULL, 'en', 'reviewed', 'self_name', NOW())
    """), {"aid": str(uuid.uuid4()), "norm": norm, "name": name, "eid": eid})
    pg.commit()
    return eid


# ─────────────────────────────────────────────────────────────────────────
# Fractional load
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_a_fractional_load_survives_storage(pg, svc, athlete):
    """227.5 lb must read back as 227.5, not 227.

    The integer column rounds, and the rounding is indistinguishable from a
    plateau: three sessions at 227.5 read back 227, 227, 227.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.data_access import effective_load

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    result = await run("log_set", {
        "exercise_index": 0, "weight": 227, "reps": 5,
        "load_value": 227.5, "load_unit": "lb",
    })
    set_id = result["logged"]["id"]

    row = pg.execute(text("""
        SELECT weight, load_value, load_unit FROM workout_log WHERE id = :id
    """), {"id": set_id}).fetchone()
    assert float(row.load_value) == 227.5
    assert row.load_unit == "lb"
    # The integer column keeps its compatibility value for shipped clients.
    assert row.weight == 227

    value, unit = effective_load({
        "weight": row.weight, "load_value": row.load_value,
        "load_unit": row.load_unit,
    })
    assert value == 227.5 and unit is Unit.LB, (
        "analytics must read the fractional pair, not the rounded integer"
    )


@requires_pg
@pytest.mark.asyncio
async def test_a_kilogram_load_is_stored_in_kilograms(pg, svc, athlete):
    """No conversion at write. 47.5 kg is 47.5 kg, labelled kg."""
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    result = await run("log_set", {
        "exercise_index": 0, "weight": 48, "reps": 5,
        "load_value": 47.5, "load_unit": "kg",
    })
    row = pg.execute(text("""
        SELECT load_value, load_unit FROM workout_log WHERE id = :id
    """), {"id": result["logged"]["id"]}).fetchone()
    assert float(row.load_value) == 47.5
    assert row.load_unit == "kg"


@requires_pg
@pytest.mark.asyncio
async def test_an_integer_only_client_still_works_and_gets_a_load_pair(
    pg, svc, athlete,
):
    """The shipped iOS build sends no fractional fields.

    Its integer is projected into the fractional pair in pounds — the legacy
    contract — so old and new rows take the same read path.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    result = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    row = pg.execute(text("""
        SELECT weight, load_value, load_unit FROM workout_log WHERE id = :id
    """), {"id": result["logged"]["id"]}).fetchone()
    assert row.weight == 225
    assert float(row.load_value) == 225.0
    assert row.load_unit == "lb"


@requires_pg
def test_a_load_without_its_unit_is_refused(pg, athlete):
    """A bare number cannot be compared against anything."""
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.performance import attach_precise_load

    wid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, set_index, weight, reps,
             set_kind, created_at)
        VALUES (:id, :w, :u, 'M7TEST Bench Press', 1, 225, 5, 'working', NOW())
    """), {"id": sid, "w": wid, "u": athlete})
    pg.commit()

    with pytest.raises(FitnessDataError) as e:
        attach_precise_load(pg, athlete, sid, load_value=227.5, load_unit=None)
    assert "needs its unit" in str(e.value)
    pg.rollback()


@requires_pg
def test_the_constraint_refuses_a_half_populated_load_pair(pg, athlete):
    wid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.commit()
    for load, unit in ((227.5, None), (None, "lb")):
        with pytest.raises(IntegrityError):
            pg.execute(text("""
                INSERT INTO workout_log
                    (id, workout_id, user_id, exercise_id, set_index, reps,
                     set_kind, load_value, load_unit, created_at)
                VALUES (:id, :w, :u, 'M7TEST Bench Press', 1, 5, 'working',
                        :load, :unit, NOW())
            """), {"id": str(uuid.uuid4()), "w": wid, "u": athlete,
                   "load": load, "unit": unit})
            pg.commit()
        pg.rollback()


@requires_pg
def test_a_bodyweight_zero_is_not_backfilled_as_a_load(pg, athlete):
    """`weight = 0` means "no external load", not "zero pounds".

    Storing it as a load would put it in a tonnage sum.
    """
    wid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, set_index, weight, reps,
             set_kind, created_at)
        VALUES (:id, :w, :u, 'M7TEST Pull Up', 1, 0, 10, 'working', NOW())
    """), {"id": sid, "w": wid, "u": athlete})
    pg.commit()
    row = pg.execute(text(
        "SELECT load_value, load_unit FROM workout_log WHERE id = :id"), {"id": sid}
    ).fetchone()
    assert row.load_value is None and row.load_unit is None


# ─────────────────────────────────────────────────────────────────────────
# Effort
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_rir_and_decimal_rpe_are_separate_scales(pg, svc, athlete):
    """They are not converted into each other.

    The conversion depends on rep range, and doing it at write would bake
    that assumption into every later comparison.
    """
    from app.services.fitness.performance import set_effort

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    with_rir = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5, "rir": 2,
    })
    with_rpe = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5, "rpe_decimal": 8.5,
    })

    rir_row = pg.execute(text(
        "SELECT rir, rpe_decimal, rpe FROM workout_log WHERE id = :id"),
        {"id": with_rir["logged"]["id"]}).fetchone()
    assert float(rir_row.rir) == 2.0
    assert rir_row.rpe_decimal is None, "RIR must not be written as an RPE"

    rpe_row = pg.execute(text(
        "SELECT rir, rpe_decimal FROM workout_log WHERE id = :id"),
        {"id": with_rpe["logged"]["id"]}).fetchone()
    assert float(rpe_row.rpe_decimal) == 8.5, (
        "the integer `rpe` column cannot hold 8.5"
    )
    assert rpe_row.rir is None

    # The reader says which scale it is on, so a caller can refuse to
    # compare across them.
    assert set_effort({"rir": 2.0, "rpe_decimal": None, "rpe": None}) == (2.0, "rir")
    assert set_effort({"rir": None, "rpe_decimal": 8.5, "rpe": None}) == (8.5, "rpe")
    assert set_effort({"rir": None, "rpe_decimal": None, "rpe": 8}) == (8.0, "rpe")
    assert set_effort({"rir": None, "rpe_decimal": None, "rpe": None}) == (None, None)


@requires_pg
def test_out_of_range_effort_is_refused(pg, athlete):
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.performance import attach_precise_load

    wid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, set_index, weight, reps,
             set_kind, created_at)
        VALUES (:id, :w, :u, 'M7TEST Bench Press', 1, 225, 5, 'working', NOW())
    """), {"id": sid, "w": wid, "u": athlete})
    pg.commit()

    for kwargs in ({"rir": 11}, {"rir": -1}, {"rpe_decimal": 0.5},
                   {"rpe_decimal": 11}, {"actual_rest_seconds": -5}):
        with pytest.raises(FitnessDataError):
            attach_precise_load(pg, athlete, sid, **kwargs)
        pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# set_role vs set_kind
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_a_top_set_is_a_working_set_with_a_role(pg, svc, athlete):
    """`set_role` is deliberately NOT a value of `set_kind`.

    Revision 125's counting rules and `workout_recalc` depend on `set_kind`
    being exactly working/warmup/drop. A top set whose `set_kind` was 'top'
    would stop counting toward the prescribed target — a real bug dressed as
    better modelling.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    top = await run("log_set", {
        "exercise_index": 0, "weight": 245, "reps": 3, "set_role": "top",
    })
    backoff = await run("log_set", {
        "exercise_index": 0, "weight": 215, "reps": 8, "set_role": "backoff",
    })

    rows = pg.execute(text("""
        SELECT set_kind, set_role, counts_toward_target
        FROM workout_log WHERE id = ANY(:ids) ORDER BY created_at
    """), {"ids": [top["logged"]["id"], backoff["logged"]["id"]]}).fetchall()
    assert [r.set_kind for r in rows] == ["working", "working"]
    assert [r.set_role for r in rows] == ["top", "backoff"]
    assert all(r.counts_toward_target for r in rows), (
        "a top set is still a working set and must count toward the target"
    )

    assert run.projection()["progress"]["completed_sets"] == 2


@requires_pg
def test_an_unknown_set_role_is_refused(pg, athlete):
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.performance import attach_precise_load

    wid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, set_index, weight, reps,
             set_kind, created_at)
        VALUES (:id, :w, :u, 'M7TEST Bench Press', 1, 225, 5, 'working', NOW())
    """), {"id": sid, "w": wid, "u": athlete})
    pg.commit()

    with pytest.raises(FitnessDataError) as e:
        attach_precise_load(pg, athlete, sid, set_role="pyramid")
    assert "roles of a working set, not values of set_kind" in str(e.value)
    pg.rollback()


@requires_pg
def test_set_kind_still_only_accepts_the_original_three(pg, athlete):
    """Revision 125's CHECK must not have been widened."""
    wid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at, updated_at)
        VALUES (:id, :u, 'M7 fixture', 'completed', NOW(), NOW())
    """), {"id": wid, "u": athlete})
    pg.commit()
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO workout_log
                (id, workout_id, user_id, exercise_id, set_index, weight, reps,
                 set_kind, created_at)
            VALUES (:id, :w, :u, 'M7TEST Bench Press', 1, 225, 5, 'top', NOW())
        """), {"id": str(uuid.uuid4()), "w": wid, "u": athlete})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Occurrences
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_successive_sets_of_one_exercise_share_an_occurrence(pg, svc, athlete):
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    ids = []
    for _ in range(3):
        result = await run("log_set", {"exercise_index": 0, "weight": 225, "reps": 5})
        ids.append(result["logged"]["id"])

    occurrences = list_occurrences(pg, athlete, run.session_id)
    assert len(occurrences) == 1
    assert occurrences[0].occurrence == 1

    linked = pg.execute(text("""
        SELECT DISTINCT exercise_performance_id FROM workout_log
        WHERE id = ANY(:ids)
    """), {"ids": ids}).fetchall()
    assert len(linked) == 1
    assert linked[0][0] == occurrences[0].id


@requires_pg
@pytest.mark.asyncio
async def test_the_same_exercise_twice_in_a_session_is_two_occurrences(
    pg, svc, athlete,
):
    """"Bench, something else, bench again" must be two blocks.

    Without it, "how did the second block compare to the first" has no
    subject at all.
    """
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 6, "reps": 5},
        {"name": "M7TEST Row", "sets": 3, "reps": 10},
    ])
    first = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    await run("log_set", {
        "exercise_index": 1, "weight": 185, "reps": 10,
    })
    second = await run("log_set", {
        "exercise_index": 0, "weight": 205, "reps": 8,
        "new_exercise_block": True,
    })

    occurrences = list_occurrences(pg, athlete, run.session_id)
    bench = [o for o in occurrences if o.captured_name == "M7TEST Bench Press"]
    assert len(bench) == 2, "the second bench block is a second occurrence"
    assert sorted(o.occurrence for o in occurrences) == [1, 2, 3], (
        "occurrence is per session, so the order the blocks happened in is readable"
    )

    first_occ = pg.execute(text(
        "SELECT exercise_performance_id FROM workout_log WHERE id = :id"),
        {"id": first["logged"]["id"]}).scalar()
    second_occ = pg.execute(text(
        "SELECT exercise_performance_id FROM workout_log WHERE id = :id"),
        {"id": second["logged"]["id"]}).scalar()
    assert first_occ != second_occ


@requires_pg
@pytest.mark.asyncio
async def test_a_variant_change_mid_session_is_a_new_occurrence(pg, svc, athlete):
    """"Switched to close grip" is a different block of work.

    The canonical id may be identical for both, which is why matching is on
    the captured name and variant rather than on it.
    """
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 6, "reps": 5},
    ])
    await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    await run("set_variant", {
        "exercise_index": 0, "variant": "M7TEST Bench Press (close grip)",
    })
    await run("log_set", {
        "exercise_index": 0, "weight": 195, "reps": 8,
    })

    occurrences = list_occurrences(pg, athlete, run.session_id)
    assert len(occurrences) == 2, (
        "a variant change is a different block, even under one snapshot slot"
    )


@requires_pg
@pytest.mark.asyncio
async def test_a_drop_segment_inherits_its_parents_occurrence(pg, svc, athlete):
    """A drop segment is part of that set, not a new block of work."""
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    parent = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    drop = await run("log_drop_segment", {
        "exercise_index": 0, "weight": 185, "reps": 5,
    })

    assert len(list_occurrences(pg, athlete, run.session_id)) == 1
    rows = pg.execute(text("""
        SELECT id, set_kind, exercise_performance_id FROM workout_log
        WHERE id = ANY(:ids)
    """), {"ids": [parent["logged"]["id"], drop["logged"]["id"]]}).fetchall()
    performance_ids = {r.exercise_performance_id for r in rows}
    assert len(performance_ids) == 1
    assert {r.set_kind for r in rows} == {"working", "drop"}


@requires_pg
@pytest.mark.asyncio
async def test_an_occurrence_records_the_canonical_id_when_it_resolves(
    pg, svc, athlete,
):
    from app.services.fitness.performance import list_occurrences

    eid = _exercise_row(pg, "M7TEST Bench Press", convention="total")
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })

    occurrence = list_occurrences(pg, athlete, run.session_id)[0]
    assert occurrence.exercise_library_id == eid
    convention = pg.execute(text("""
        SELECT captured_load_convention FROM fitness_exercise_performance
        WHERE id = :id
    """), {"id": occurrence.id}).scalar()
    assert convention == "total"


@requires_pg
@pytest.mark.asyncio
async def test_an_unresolvable_name_leaves_the_canonical_id_null(pg, svc, athlete):
    """The set stays attributed to the text name it was logged under.

    Guessing would credit it to a lift the athlete may never have done, and
    the mistake would be invisible.
    """
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Some Lift Nobody Named", "sets": 3, "reps": 5},
    ])
    await run("log_set", {
        "exercise_index": 0, "weight": 100, "reps": 10,
    })
    occurrence = list_occurrences(pg, athlete, run.session_id)[0]
    assert occurrence.exercise_library_id is None
    assert occurrence.captured_name == "M7TEST Some Lift Nobody Named"


@requires_pg
@pytest.mark.asyncio
async def test_occurrence_numbers_are_unique_within_a_session(pg, svc, athlete):
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    pg.commit()
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO fitness_exercise_performance
                (id, user_id, active_session_id, occurrence, captured_name)
            VALUES (:id, :u, :sid, 1, 'M7TEST Duplicate')
        """), {"id": str(uuid.uuid4()), "u": athlete, "sid": run.session_id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_an_occurrence_cannot_be_created_for_a_foreign_session(pg, athlete):
    from app.services.fitness.performance import ensure_occurrence

    other = f"m7-other-{uuid.uuid4().hex[:12]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW())
    """), {"id": other, "e": f"{other}@m7.invalid", "p": "$2b$12$" + "x" * 53})
    sid = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO active_workout_session (id, user_id, status, started_at, version)
        VALUES (:id, :u, 'active', NOW(), 1)
    """), {"id": sid, "u": other})
    pg.commit()
    try:
        with pytest.raises(LookupError):
            ensure_occurrence(pg, athlete, sid, captured_name="M7TEST Bench Press")
        pg.rollback()
    finally:
        pg.execute(text("DELETE FROM active_workout_session WHERE id = :id"), {"id": sid})
        pg.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": other})
        pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Correction and concurrency still work
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_a_revision_keeps_the_occurrence_and_updates_the_load(pg, svc, athlete):
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    logged = await run("log_set", {
        "exercise_index": 0, "weight": 315, "reps": 5,
        "load_value": 315.0, "load_unit": "lb",
    })
    before = pg.execute(text(
        "SELECT exercise_performance_id FROM workout_log WHERE id = :id"),
        {"id": logged["logged"]["id"]}).scalar()

    await run("revise_set", {
        "set_id": logged["logged"]["id"], "weight": 135, "reps": 5,
    })

    # The revision produces a new row through the same `_insert_set` path, so
    # it gets its own occurrence link — to the same occurrence.
    assert len(list_occurrences(pg, athlete, run.session_id)) == 1
    live = pg.execute(text("""
        SELECT id, weight, exercise_performance_id FROM workout_log
        WHERE active_session_id = :sid AND voided_at IS NULL
    """), {"sid": run.session_id}).fetchall()
    assert [r.weight for r in live] == [135]
    assert live[0].exercise_performance_id == before


@requires_pg
@pytest.mark.asyncio
async def test_a_replayed_command_does_not_create_a_second_occurrence(
    pg, svc, athlete,
):
    """Idempotency is the command service's, and must survive this wiring."""
    from app.services.fitness.performance import list_occurrences

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    envelope = {
        "command_id": str(uuid.uuid4()),
        "kind": "log_set",
        "payload": {"exercise_index": 0, "weight": 225, "reps": 5},
        "origin_device": "web",
    }
    first = await svc.execute(pg, athlete, envelope)
    second = await svc.execute(pg, athlete, envelope)

    assert second["status"] == "replayed"
    assert len(list_occurrences(pg, athlete, run.session_id)) == 1
    assert pg.execute(text("""
        SELECT COUNT(*) FROM workout_log WHERE active_session_id = :sid
    """), {"sid": run.session_id}).scalar() == 1


@requires_pg
@pytest.mark.asyncio
async def test_a_set_is_still_stored_when_the_metadata_attachment_fails(
    pg, svc, athlete, monkeypatch,
):
    """The set is what the athlete asked for; the metadata is derived.

    A failure to attach derived metadata must not lose a logged set.
    """
    import app.services.fitness.performance as perf

    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    monkeypatch.setattr(
        perf, "ensure_occurrence",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    row = pg.execute(text("""
        SELECT weight, reps, exercise_performance_id FROM workout_log WHERE id = :id
    """), {"id": result["logged"]["id"]}).fetchone()
    assert (row.weight, row.reps) == (225, 5)
    assert row.exercise_performance_id is None


# ─────────────────────────────────────────────────────────────────────────
# PR retraction and promotion
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
@pytest.mark.asyncio
async def test_voiding_a_set_retracts_its_pr_and_promotes_the_next_best(
    pg, svc, athlete,
):
    """Retracting without promoting leaves no PR for a lift that has a best.

    That is strictly worse than the stale answer, so the next eligible set is
    flagged.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 5, "reps": 5},
    ])
    lighter = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    heavier = await run("log_set", {
        "exercise_index": 0, "weight": 315, "reps": 5,
    })

    await run("void_set", {
        "set_id": heavier["logged"]["id"], "reason": "wrong bar",
    })

    live = pg.execute(text("""
        SELECT COUNT(*) FROM exercise_pr
        WHERE workout_set_id = :s AND withdrawn_at IS NULL
    """), {"s": heavier["logged"]["id"]}).scalar()
    assert live == 0, "a voided set holds no live PR"

    retracted = pg.execute(text("""
        SELECT withdrawn_reason FROM exercise_pr WHERE workout_set_id = :s
    """), {"s": heavier["logged"]["id"]}).scalar()
    assert retracted, "the retracted claim stays, with its reason"

    # The remaining eligible set is flagged as the next record.
    assert pg.execute(text(
        "SELECT is_pr FROM workout_log WHERE id = :id"),
        {"id": lighter["logged"]["id"]}).scalar() is True


@requires_pg
@pytest.mark.asyncio
async def test_promotion_never_picks_a_voided_set(pg, svc, athlete):
    """A voided set cannot hold a record — that is why the claim was retracted."""
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 5, "reps": 5},
    ])
    first = await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    second = await run("log_set", {
        "exercise_index": 0, "weight": 315, "reps": 5,
    })
    await run("void_set", {
        "set_id": first["logged"]["id"], "reason": "miscounted",
    })
    await run("void_set", {
        "set_id": second["logged"]["id"], "reason": "wrong bar",
    })

    flagged = pg.execute(text("""
        SELECT id FROM workout_log
        WHERE active_session_id = :sid AND is_pr = true
    """), {"sid": run.session_id}).fetchall()
    assert flagged == [], (
        "with every eligible set voided there is no recorded best, and "
        "claiming one would be an invention"
    )


@requires_pg
@pytest.mark.asyncio
async def test_a_voided_set_does_not_promote_itself(pg, svc, athlete):
    """The ordering trap, pinned.

    `_apply_void_set` calls `withdraw_prs_for_set` BEFORE it stamps
    `voided_at`, so the set being voided is still live from the promotion
    query's point of view and would promote itself straight back — the PR
    would survive the void that was supposed to retract it. The exclusion is
    explicit rather than relying on the caller's statement order.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 5, "reps": 5},
    ])
    only = await run("log_set", {"exercise_index": 0, "weight": 315, "reps": 5})
    await run("void_set", {"set_id": only["logged"]["id"], "reason": "wrong bar"})

    row = pg.execute(text("""
        SELECT is_pr, voided_at FROM workout_log WHERE id = :id
    """), {"id": only["logged"]["id"]}).fetchone()
    assert row.voided_at is not None
    assert row.is_pr is False, "a voided set must not be flagged as the record"


@requires_pg
@pytest.mark.asyncio
async def test_a_withdrawn_record_does_not_block_a_later_real_one(pg, svc, athlete):
    """The corrected-down case.

    Correcting a mistaken 315 to 135 must leave the athlete with 135 as
    their record, not with nothing because the retracted 315 still wins the
    comparison.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 5, "reps": 5},
    ])
    logged = await run("log_set", {
        "exercise_index": 0, "weight": 315, "reps": 5,
    })
    await run("revise_set", {
        "set_id": logged["logged"]["id"], "weight": 135, "reps": 5,
    })

    live = pg.execute(text("""
        SELECT weight FROM exercise_pr
        WHERE user_id = :u AND withdrawn_at IS NULL
    """), {"u": athlete}).fetchall()
    assert [int(r.weight) for r in live] == [135]


@requires_pg
@pytest.mark.asyncio
async def test_a_new_pr_records_its_formula_version(pg, svc, athlete):
    """So a later change to the e1RM formula cannot reinterpret old records.

    The stamp is `brzycki_v1`, not `epley_v1`: the PR ledger's writer is
    `calculate_estimated_1rm`, which is Brzycki (`weight * 36 / (37 - reps)`,
    capped at 12 reps). It was labelled `epley_v1` until Step 16 — a
    mislabel, and exactly the kind the version stamp exists to prevent, since
    a reader reconciling old rows would have applied the wrong formula.
    The analytics module uses Epley deliberately; Step 18 reconciles the two.
    """
    run = await _start(svc, pg, athlete, [
        {"name": "M7TEST Bench Press", "sets": 3, "reps": 5},
    ])
    await run("log_set", {
        "exercise_index": 0, "weight": 225, "reps": 5,
    })
    row = pg.execute(text("""
        SELECT pr_kind, formula_version, load_unit FROM exercise_pr
        WHERE user_id = :u
    """), {"u": athlete}).fetchone()
    assert row.pr_kind == "estimated_1rm"
    assert row.formula_version == "brzycki_v1"
    assert row.load_unit == "lb"
