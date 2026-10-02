"""Step 29 of FITNESS_COACH_IMPLEMENTATION_PLAN: versioned programs.

Programming data in this codebase lives in three places that can disagree:
`fitness_template.exercises` (the JSON the live workout view reads),
`template_exercise` (the relational rows the editor writes), and
`exercises[i].set_plan` (a top/backoff table keyed by *program* week). Most
of this file is about the consequences of that, and the rest is about the
line between a draft and a live program.

Four claims:

* **One typed shape, parsed from either side.** A top/backoff week does not
  flatten into three identical sets, and "4+" is not the same as 4.
* **One writer.** Both projections are rebuilt from the typed source in one
  transaction, and a `set_plan` survives an edit made through the old route.
* **The model drafts; a person activates.** An acceptance attributed to a
  model is refused by the service and by the database, and a draft with a
  blocking finding or an open question cannot be activated at all.
* **The past does not move.** Activating a revision writes new rows. A
  completed session and a stored review's input state are untouched, and an
  activated revision is frozen.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_programming_pg.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

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
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"s29a-{uuid.uuid4().hex[:17]}"
    bob = f"s29b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s29.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_program_draft", "fitness_template_revision",
                  "fitness_program_revision", "workout_log", "workout",
                  "fitness_pain_report", "fitness_athlete_limitation",
                  "fitness_athlete_goal", "fitness_athlete_profile",
                  "daily_recovery_log"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
            pg.commit()
        except Exception:
            pg.rollback()
    for table in ("template_exercise",):
        try:
            pg.execute(text(f"""
                DELETE FROM {table} WHERE template_id IN (
                    SELECT id FROM fitness_template WHERE user_id = ANY(:ids)
                )
            """), {"ids": [alice, bob]})
            pg.commit()
        except Exception:
            pg.rollback()
    for table in ("fitness_template", "fitness_phase", "fitness_program",
                  "exercise_library"):
        try:
            column = (
                "owner_user_id" if table == "exercise_library" else "user_id"
            )
            pg.execute(text(
                f"DELETE FROM {table} WHERE {column} = ANY(:ids)"
            ), {"ids": [alice, bob]})
            pg.commit()
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _library(pg, user_id, name, *, equipment=("barbell",),
             contraindications=(), movement="horizontal_press"):
    exercise_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO exercise_library (
            id, name, normalized_name, movement_pattern, muscle_groups,
            equipment_required, injury_contraindications, difficulty_level,
            owner_user_id, visibility, load_convention, created_at, updated_at
        ) VALUES (
            :id, :name, :normalized, :movement, CAST('["chest"]' AS JSONB),
            CAST(:equipment AS JSONB), CAST(:contra AS JSONB), 3,
            :u, 'private', 'total', NOW(), NOW()
        )
    """), {
        "id": exercise_id, "name": name, "normalized": name.strip().lower(),
        "movement": movement, "equipment": json.dumps(list(equipment)),
        "contra": json.dumps(list(contraindications)), "u": user_id,
    })
    pg.commit()
    return exercise_id


def _profile(pg, user_id, **over):
    body = {
        "equipment": ["barbell", "rack", "bench"],
        "available_days": ["monday", "wednesday", "friday"],
        "preferred_duration_minutes": 75,
        "training_level": "advanced",
        "training_experience_years": 6,
        "excluded_exercise_ids": [],
    }
    body.update(over)
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (
            id, user_id, equipment, available_days,
            preferred_duration_minutes, training_level,
            training_experience_years, excluded_exercise_ids,
            preferred_exercise_ids, dietary_restrictions,
            dietary_preferences, supplements, calculation_sex,
            coaching_style, monitoring_consent, timezone, weight_unit,
            length_unit, row_version, created_at, updated_at
        ) VALUES (
            :id, :u, CAST(:equipment AS JSONB),
            CAST(:available_days AS JSONB), :minutes, :level, :years,
            CAST(:excluded AS JSONB), '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
            '[]'::jsonb, 'male', 'unset', FALSE, 'America/New_York', 'lb',
            'in', 1, NOW(), NOW()
        )
        ON CONFLICT (user_id) DO UPDATE SET
            equipment = EXCLUDED.equipment,
            available_days = EXCLUDED.available_days,
            preferred_duration_minutes = EXCLUDED.preferred_duration_minutes,
            training_level = EXCLUDED.training_level,
            training_experience_years = EXCLUDED.training_experience_years,
            excluded_exercise_ids = EXCLUDED.excluded_exercise_ids
    """), {
        "id": str(uuid.uuid4()), "u": user_id,
        "equipment": json.dumps(body["equipment"]),
        "available_days": json.dumps(body["available_days"]),
        "minutes": body["preferred_duration_minutes"],
        "level": body["training_level"], "years": body["training_experience_years"],
        "excluded": json.dumps(body["excluded_exercise_ids"]),
    })
    pg.commit()


def _program_and_phase(pg, user_id):
    program_id = str(uuid.uuid4())
    phase_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_program (
            id, user_id, name, goal, is_active, created_at
        ) VALUES (
            :id, :u, 'Test program', 'strength', TRUE, CURRENT_TIMESTAMP
        )
    """), {"id": program_id, "u": user_id})
    pg.execute(text("""
        INSERT INTO fitness_phase (
            id, user_id, name, program_id, start_date, end_date, status,
            order_index, duration_weeks, created_at
        ) VALUES (
            :id, :u, 'Block 1', :program, CURRENT_DATE - 7,
            CURRENT_DATE + 21, 'active', 1, 4, CURRENT_TIMESTAMP
        )
    """), {"id": phase_id, "u": user_id, "program": program_id})
    pg.commit()
    return program_id, phase_id


def _template(pg, user_id, phase_id, *, name="Upper A", exercises=None,
              scheduled=("monday",)):
    template_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_template (
            id, phase_id, user_id, name, scheduled_days, exercises,
            order_in_phase, day_of_week, current_revision,
            created_at, updated_at
        ) VALUES (
            :id, :phase, :u, :name, :scheduled, :exercises, 0, 0, 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """), {
        "id": template_id, "phase": phase_id, "u": user_id, "name": name,
        "scheduled": json.dumps(list(scheduled)),
        "exercises": json.dumps(exercises if exercises is not None else [{
            "name": "Barbell Bench Press", "sets": 3, "reps": "5-8",
            "rpe_target": 8, "rest_seconds": 180,
            "progression_rule": "DOUBLE_PROGRESSION",
        }]),
    })
    pg.commit()
    return template_id


# ─────────────────────────────────────────────────────────────────────────
# The typed parser
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("8-10", (8, 10)),
    ("8–10", (8, 10)),
    ("5", (5, 5)),
    (12, (12, 12)),
    ("4+", (4, None)),
    ("3 to 5", (3, 5)),
    ("AMRAP", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_rep_targets_parse(value, expected):
    """"4+" is a floor with no ceiling, which is NOT 4. Collapsing it would
    prescribe a hard four where the plan wanted at least four."""
    from app.services.fitness.programming import parse_reps

    assert parse_reps(value) == expected


def test_a_top_backoff_week_does_not_flatten():
    """A plan-driven lift's loading table is the prescription. A parser that
    only read the flat fields would turn a top set plus two backoffs into
    three identical sets, and the athlete would be told to do the top set
    three times."""
    from app.services.fitness.programming import parse_slot
    from app.schemas.fitness_coach import SetRole

    spec = {
        "name": "Barbell Bench Press", "sets": 3, "reps": "5-8",
        "rpe_target": 8, "rest_seconds": 180,
        "set_plan": {
            "kind": "top_backoff",
            "warmup": [{"reps": 5, "pct": 0.5}, {"reps": 3, "pct": 0.7}],
            "weeks": {
                "2": {"sets": [
                    {"role": "top", "reps": "2-4", "rpe": 8, "sets": 1},
                    {"role": "backoff", "reps": "6-8", "pct": 0.85, "sets": 2},
                ]},
            },
        },
    }
    slot = parse_slot(spec, week=2)
    roles = [one.role for one in slot.sets]
    assert roles == [
        SetRole.WARMUP, SetRole.WARMUP, SetRole.TOP,
        SetRole.BACKOFF, SetRole.BACKOFF,
    ]
    # Warmups are not working sets.
    assert slot.working_sets == 3
    top = slot.sets[2]
    assert (top.reps_low, top.reps_high) == (2, 4)
    assert top.rpe == 8
    backoff = slot.sets[3]
    # A set_plan percentage is a fraction; a typed one is a percentage.
    # Reading 0.85 as 0.85% would prescribe an empty bar.
    assert backoff.load_percent == 85.0


def test_a_week_with_no_plan_entry_falls_back_to_the_flat_fields():
    """`set_plan` is keyed by program week, and a week it does not cover is
    ordinary programming rather than an error."""
    from app.services.fitness.programming import parse_slot

    spec = {
        "name": "Barbell Row", "sets": 4, "reps": "8-12", "rpe_target": 7,
        "set_plan": {"kind": "top_backoff", "weeks": {"1": {"sets": [
            {"role": "top", "reps": 5, "rpe": 9},
        ]}}},
    }
    slot = parse_slot(spec, week=9)
    assert slot.working_sets == 4
    assert all(one.rpe == 7 for one in slot.sets)


def test_a_percentage_slot_with_no_reference_is_not_called_percentage():
    """The typed shape refuses PERCENTAGE without a reference max, and
    inventing one would invent the loads."""
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness.programming import parse_slot

    slot = parse_slot({
        "name": "Squat", "progression_rule": "percentage",
        "set_plan": {"kind": "top_backoff", "weeks": {"1": {"sets": [
            {"role": "top", "reps": 3, "pct": 0.9},
        ]}}},
    }, week=1)
    assert slot.progression is ProgressionRule.MANUAL


def test_a_time_metric_slot_carries_seconds_not_reps():
    from app.schemas.fitness_coach import MetricType
    from app.services.fitness.programming import parse_slot

    slot = parse_slot({
        "name": "Plank", "sets": 3, "reps": "45", "metric_type": "time",
    })
    assert slot.sets[0].metric is MetricType.TIME
    assert slot.sets[0].seconds == 45
    assert slot.sets[0].reps is None


def test_a_set_cannot_carry_both_a_weight_and_a_percentage():
    from app.schemas.fitness_coach import PrescribedSet, Unit

    with pytest.raises(Exception) as excinfo:
        PrescribedSet(index=0, reps=5, load_kg=100, load_unit=Unit.KG,
                      load_percent=80)
    assert "not both" in str(excinfo.value)


def test_a_prescribed_load_needs_its_unit():
    """This codebase stores kilograms and displays pounds, and a bare number
    has been wrong in both directions."""
    from app.schemas.fitness_coach import PrescribedSet

    with pytest.raises(Exception) as excinfo:
        PrescribedSet(index=0, reps=5, load_kg=100)
    assert "needs its unit" in str(excinfo.value)


def test_a_time_set_with_a_rep_target_is_rejected():
    from app.schemas.fitness_coach import MetricType, PrescribedSet

    with pytest.raises(Exception) as excinfo:
        PrescribedSet(index=0, metric=MetricType.TIME, seconds=60, reps=10)
    assert "contradicts itself" in str(excinfo.value)


def test_an_inverted_rep_range_is_rejected():
    from app.schemas.fitness_coach import PrescribedSet

    with pytest.raises(Exception) as excinfo:
        PrescribedSet(index=0, reps_low=12, reps_high=5)
    assert "inverted" in str(excinfo.value)


@requires_pg
def test_reading_a_template_produces_the_typed_session(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id)

    session = programming.read_session(pg, alice, template_id)
    assert session.name == "Upper A"
    assert session.scheduled_days == ["monday"]
    assert len(session.slots) == 1
    assert session.slots[0].exercise_name == "Barbell Bench Press"
    assert session.working_sets == 3


@requires_pg
def test_one_athlete_cannot_read_anothers_template(pg, two_athletes):
    from app.services.fitness import programming

    alice, bob = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id)
    with pytest.raises(LookupError):
        programming.read_session(pg, bob, template_id)


# ─────────────────────────────────────────────────────────────────────────
# The one writer: both projections, in parity
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_writing_a_session_fills_both_projections(pg, two_athletes):
    """§29.1. The JSON the live workout view reads and the relational rows
    the editor reads are written from the same typed source, in one
    transaction."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id)

    session = programming.read_session(pg, alice, template_id)
    revision = programming.write_session(pg, alice, template_id, session)
    assert revision == 1

    json_side = pg.execute(text("""
        SELECT exercises, current_revision FROM fitness_template
        WHERE id = :id
    """), {"id": template_id}).fetchone()
    exercises = json.loads(json_side.exercises) if isinstance(
        json_side.exercises, str) else json_side.exercises
    assert [one["name"] for one in exercises] == ["Barbell Bench Press"]
    assert json_side.current_revision == 1

    rows = pg.execute(text("""
        SELECT exercise_name, target_sets, rep_range_low, rep_range_high,
               target_rpe
        FROM template_exercise WHERE template_id = :id
        ORDER BY order_index
    """), {"id": template_id}).fetchall()
    assert [row.exercise_name for row in rows] == ["Barbell Bench Press"]
    assert rows[0].target_sets == 3
    assert (rows[0].rep_range_low, rows[0].rep_range_high) == (5, 8)
    assert float(rows[0].target_rpe) == 8.0


@requires_pg
def test_the_two_projections_agree_after_a_write(pg, two_athletes):
    """The parity check the plan asks for: JSON and normalized, same
    numbers."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id, exercises=[
        {"name": "Barbell Bench Press", "sets": 4, "reps": "5-8",
         "rpe_target": 8, "rest_seconds": 180},
        {"name": "Barbell Row", "sets": 3, "reps": "8-12", "rpe_target": 7,
         "rest_seconds": 120},
    ])
    session = programming.read_session(pg, alice, template_id)
    programming.write_session(pg, alice, template_id, session)

    json_row = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :id"
    ), {"id": template_id}).scalar()
    exercises = json.loads(json_row) if isinstance(json_row, str) else json_row
    rows = pg.execute(text("""
        SELECT exercise_name, target_sets, rep_range_low, rep_range_high,
               target_rpe, rest_seconds
        FROM template_exercise WHERE template_id = :id
        ORDER BY order_index
    """), {"id": template_id}).fetchall()

    assert len(exercises) == len(rows) == 2
    for spec, row in zip(exercises, rows):
        assert spec["name"] == row.exercise_name
        assert spec["sets"] == row.target_sets
        assert spec["rep_range_low"] == row.rep_range_low
        assert spec["rep_range_high"] == row.rep_range_high
        assert spec["rpe_target"] == float(row.target_rpe)
        assert spec["rest_seconds"] == row.rest_seconds


@requires_pg
def test_a_set_plan_survives_a_write(pg, two_athletes):
    """The top/backoff table is richer than the flat JSON projection, so a
    writer that re-derived the JSON would strip it off every plan-driven
    lift the first time its template was touched. That is a bug this
    codebase already had once."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    plan = {
        "kind": "top_backoff",
        "weeks": {"1": {"sets": [{"role": "top", "reps": 3, "rpe": 9}]}},
    }
    template_id = _template(pg, alice, phase_id, exercises=[{
        "name": "Barbell Bench Press", "sets": 3, "reps": "5-8",
        "rpe_target": 8, "set_plan": plan,
    }])

    session = programming.read_session(pg, alice, template_id)
    programming.write_session(pg, alice, template_id, session)

    stored = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :id"
    ), {"id": template_id}).scalar()
    exercises = json.loads(stored) if isinstance(stored, str) else stored
    assert exercises[0]["set_plan"] == plan


@requires_pg
def test_the_legacy_route_sync_versions_the_template(pg, two_athletes):
    """`routes/fitness.py` edits `template_exercise` directly, and §29.1
    asks for one writer. The route's synchroniser now goes through it, so
    an edit made the old way is versioned like any other."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id)

    pg.execute(text("""
        INSERT INTO template_exercise (
            id, template_id, exercise_name, order_index, target_sets,
            rep_range_low, rep_range_high, target_rpe, rest_seconds,
            progression_rule, metric_type, is_per_side, created_at, updated_at
        ) VALUES (
            :id, :t, 'Barbell Row', 0, 4, 8, 12, 7.5, 120, 'LINEAR',
            'reps', FALSE, NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "t": template_id})
    pg.commit()

    revision = programming.sync_projections(pg, alice, template_id)
    pg.commit()
    assert revision == 1

    stored = pg.execute(text(
        "SELECT exercises, current_revision FROM fitness_template "
        "WHERE id = :id"
    ), {"id": template_id}).fetchone()
    exercises = json.loads(stored.exercises) if isinstance(
        stored.exercises, str) else stored.exercises
    assert [one["name"] for one in exercises] == ["Barbell Row"]
    assert stored.current_revision == 1
    snapshot_count = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_template_revision
        WHERE template_id = :id
    """), {"id": template_id}).scalar()
    assert snapshot_count == 1


@requires_pg
def test_a_template_revision_is_frozen_once_activated(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id)
    session = programming.read_session(pg, alice, template_id)
    programming.write_session(pg, alice, template_id, session)

    revision_id = pg.execute(text("""
        SELECT id FROM fitness_template_revision WHERE template_id = :id
    """), {"id": template_id}).scalar()
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        pg.execute(text("""
            UPDATE fitness_template_revision
            SET snapshot = '{"name": "rewritten"}'::jsonb WHERE id = :id
        """), {"id": revision_id})
        pg.commit()
    assert "frozen" in str(excinfo.value)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Validation (§29.3)
# ─────────────────────────────────────────────────────────────────────────

def _draft(**over):
    from app.schemas.fitness_coach import (
        DraftBlockKind, EffortTarget, PrescribedSession, PrescribedSet,
        PrescribedSlot, PrescribedWeek, ProgramDraftV1, SetRole,
    )

    def working(index, **kwargs):
        body = {
            "index": index, "role": SetRole.WORKING, "reps_low": 5,
            "reps_high": 8, "effort": EffortTarget.RPE, "rpe": 8.5,
            "rest_seconds": 180,
        }
        body.update(kwargs)
        return PrescribedSet(**body)

    slots = over.pop("slots", None) or [PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        sets=[working(0), working(1), working(2), working(3)],
    )]
    sessions = over.pop("sessions", None) or [PrescribedSession(
        name="Upper A", day_of_week=0, scheduled_days=["monday"],
        slots=slots,
    )]
    weeks = over.pop("weeks", None) or [PrescribedWeek(
        program_week=1, sessions=sessions,
    )]
    body = {
        "kind": DraftBlockKind.BLOCK,
        "title": "Four-week upper block",
        "rationale": "Bench has stalled; adding a top set and backoffs.",
        "addresses_goals": ["add 10kg to the bench"],
        "weeks": weeks,
    }
    body.update(over)
    return ProgramDraftV1(**body)


@requires_pg
def test_a_clean_draft_validates(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))
    _goal(pg, alice)

    validation = programming.validate_draft(pg, alice, _draft())
    assert validation.acceptable, [one.message for one in validation.blocking]


def _goal(pg, user_id, kind="strength", rationale="add 10kg to the bench",
          primary=True):
    pg.execute(text("""
        INSERT INTO fitness_athlete_goal (
            id, user_id, kind, is_primary, priority, rationale, rate_basis,
            valid_from, recorded_at, source
        ) VALUES (
            :id, :u, :kind, :primary, :priority, :rationale, 'none',
            CURRENT_DATE - 30, NOW(), 'user'
        )
    """), {
        "id": str(uuid.uuid4()), "u": user_id, "kind": kind,
        "primary": primary, "priority": 1 if primary else 2,
        "rationale": rationale,
    })
    pg.commit()


@requires_pg
def test_an_unknown_exercise_blocks_the_draft(pg, two_athletes):
    """A name that resolves to nothing has no history to progress from and
    no contraindications to check."""
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)

    validation = programming.validate_draft(pg, alice, _draft())
    codes = {one.code for one in validation.blocking}
    assert DraftValidationCode.UNKNOWN_EXERCISE in codes
    assert not validation.acceptable


@requires_pg
def test_missing_equipment_blocks_the_draft(pg, two_athletes):
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice, equipment=["dumbbells"])
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    validation = programming.validate_draft(pg, alice, _draft())
    codes = {one.code for one in validation.blocking}
    assert DraftValidationCode.EQUIPMENT_UNAVAILABLE in codes
    message = next(
        one.message for one in validation.blocking
        if one.code is DraftValidationCode.EQUIPMENT_UNAVAILABLE
    )
    assert "barbell" in message


@requires_pg
def test_an_excluded_exercise_blocks_the_draft(pg, two_athletes):
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press",
                           equipment=("barbell", "bench"))
    _profile(pg, alice, excluded_exercise_ids=[exercise_id])
    _goal(pg, alice)

    validation = programming.validate_draft(pg, alice, _draft())
    assert DraftValidationCode.LIMITATION_CONFLICT in {
        one.code for one in validation.blocking
    }


@requires_pg
def test_a_limitation_is_respected_without_being_diagnosed(pg, two_athletes):
    """§29.3: respect the limitation without a diagnosis. The finding names
    the recorded area and the exercise — never a condition, a cause or a
    treatment."""
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(
        pg, alice, "Barbell Bench Press",
        equipment=("barbell", "bench"), contraindications=("shoulder",),
    )
    _profile(pg, alice)
    _goal(pg, alice)
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation (
            id, user_id, area, description, excluded_exercise_ids,
            modified_exercise_ids, severity_flag, effective_from, status,
            created_at, updated_at
        ) VALUES (
            :id, :u, 'shoulder',
            'left shoulder hurts on heavy pressing since August',
            '[]'::jsonb, '[]'::jsonb, 'moderate', CURRENT_DATE - 30,
            'active', NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    validation = programming.validate_draft(pg, alice, _draft())
    conflicts = [
        one for one in validation.findings
        if one.code is DraftValidationCode.LIMITATION_CONFLICT
    ]
    assert conflicts
    text_all = " ".join(one.message for one in validation.findings).lower()
    assert "shoulder" in text_all
    # No diagnosis, no cause, no treatment.
    for forbidden in ("impingement", "tendinitis", "tear", "rotator cuff",
                      "see a doctor", "physio", "rest it", "ice"):
        assert forbidden not in text_all, forbidden


@requires_pg
def test_an_implausible_session_duration_blocks(pg, two_athletes):
    from app.schemas.fitness_coach import (
        DraftValidationCode, EffortTarget, PrescribedSet, PrescribedSlot,
        SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    huge = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        sets=[
            PrescribedSet(
                index=index, role=SetRole.WORKING, reps_low=8, reps_high=10,
                effort=EffortTarget.RPE, rpe=8, rest_seconds=300,
            )
            for index in range(39)
        ],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[huge]))
    codes = {one.code for one in validation.blocking}
    assert DraftValidationCode.IMPLAUSIBLE_DURATION in codes


@requires_pg
def test_a_session_of_two_sets_is_not_a_session(pg, two_athletes):
    from app.schemas.fitness_coach import (
        DraftValidationCode, PrescribedSet, PrescribedSlot, SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    tiny = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        sets=[PrescribedSet(
            index=0, role=SetRole.WORKING, reps=5, rest_seconds=0,
        )],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[tiny]))
    assert DraftValidationCode.IMPLAUSIBLE_DURATION in {
        one.code for one in validation.blocking
    }


@requires_pg
def test_an_experienced_lifter_does_not_get_a_beginner_plan(pg, two_athletes):
    """§29.3: no beginner default if experienced history or profile. Checked
    on the loading, not the prose: a plan where nothing passes RPE 8 and
    nothing carries more than three working sets is the template a model
    reaches for when it has not read the history."""
    from app.schemas.fitness_coach import (
        DraftValidationCode, EffortTarget, PrescribedSet, PrescribedSlot,
        SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice, training_level="advanced", training_experience_years=8)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    novice = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        sets=[
            PrescribedSet(
                index=index, role=SetRole.WORKING, reps=10,
                effort=EffortTarget.RPE, rpe=6, rest_seconds=90,
            )
            for index in range(3)
        ],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[novice]))
    codes = {one.code for one in validation.blocking}
    assert DraftValidationCode.BEGINNER_DEFAULT_REJECTED in codes
    message = next(
        one.message for one in validation.blocking
        if one.code is DraftValidationCode.BEGINNER_DEFAULT_REJECTED
    )
    assert "advanced" in message


@requires_pg
def test_a_novice_profile_does_get_a_novice_plan(pg, two_athletes):
    """The same draft, for somebody with no history, is fine. A check that
    fired on everybody would just be an outage."""
    from app.schemas.fitness_coach import (
        DraftValidationCode, EffortTarget, PrescribedSet, PrescribedSlot,
        SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice, training_level="novice", training_experience_years=0)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    novice = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        sets=[
            PrescribedSet(
                index=index, role=SetRole.WORKING, reps=10,
                effort=EffortTarget.RPE, rpe=6, rest_seconds=90,
            )
            for index in range(3)
        ],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[novice]))
    assert DraftValidationCode.BEGINNER_DEFAULT_REJECTED not in {
        one.code for one in validation.findings
    }


@requires_pg
def test_logged_history_alone_makes_an_athlete_experienced(pg, two_athletes):
    """Either signal is enough. Somebody with two hundred logged sessions
    and a blank profile is not a novice."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice, training_level="unknown", training_experience_years=None)
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    for day in range(45):
        workout_id = _workout(pg, alice, days_ago=day)
        pg.execute(text("""
            INSERT INTO workout_log (
                id, workout_id, user_id, exercise_id, set_index, reps,
                load_value, load_unit, session_date, created_at
            ) VALUES (
                :id, :w, :u, :ex, 0, 5, 100, 'kg', CURRENT_DATE - :offset,
                NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "w": workout_id, "u": alice,
            "ex": exercise_id, "offset": day,
        })
    pg.commit()

    constraints = programming.load_constraints(pg, alice)
    assert constraints.logged_sessions >= 40
    assert constraints.is_experienced is True


@requires_pg
def test_a_missing_constraint_asks_rather_than_defaulting(pg, two_athletes):
    """§29.3. A question costs a day; a guessed constraint costs the
    block."""
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    # No profile at all: no equipment, no days, no goals.
    _library(pg, alice, "Barbell Bench Press", equipment=())

    validation = programming.validate_draft(pg, alice, _draft())
    questions = validation.questions
    assert questions
    joined = " ".join(one.message for one in questions).lower()
    assert "equipment" in joined
    assert DraftValidationCode.MISSING_CONSTRAINT in {
        one.code for one in validation.findings
    }


@requires_pg
def test_percentage_work_with_no_reference_asks(pg, two_athletes):
    from app.schemas.fitness_coach import (
        EffortTarget, PrescribedSet, PrescribedSlot, ProgressionRule, SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    slot = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        progression=ProgressionRule.PERCENTAGE,
        sets=[PrescribedSet(
            index=index, role=SetRole.WORKING, reps=3,
            effort=EffortTarget.NONE, rest_seconds=180,
        ) for index in range(4)],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[slot]))
    joined = " ".join(one.message for one in validation.questions)
    assert "reference max" in joined


@requires_pg
def test_a_day_outside_the_available_week_is_a_question(pg, two_athletes):
    from app.services.fitness import programming
    from app.schemas.fitness_coach import PrescribedSession

    alice, _ = two_athletes
    _profile(pg, alice, available_days=["monday", "wednesday"])
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press",
             equipment=("barbell", "bench"))

    draft = _draft()
    sunday = PrescribedSession(
        name="Upper A", day_of_week=6, scheduled_days=["sunday"],
        slots=draft.weeks[0].sessions[0].slots,
    )
    validation = programming.validate_draft(
        pg, alice, _draft(sessions=[sunday]),
    )
    joined = " ".join(one.message for one in validation.findings).lower()
    assert "sunday" in joined


# ─────────────────────────────────────────────────────────────────────────
# Drafts: store, preview, accept
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ready(pg, two_athletes):
    """An athlete with a program, a phase, a library and a clean profile."""
    alice, bob = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press", equipment=("barbell", "bench"))
    _library(pg, alice, "Barbell Row", equipment=("barbell",))
    program_id, phase_id = _program_and_phase(pg, alice)
    return alice, bob, program_id, phase_id


@requires_pg
def test_storing_a_draft_activates_nothing(pg, ready):
    """§29.2. The draft exists; no template moved."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    before = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_template WHERE user_id = :u
    """), {"u": alice}).scalar()

    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    assert stored.status.value == "draft"
    assert stored.validation.acceptable

    after = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_template WHERE user_id = :u
    """), {"u": alice}).scalar()
    assert after == before
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_a_second_draft_supersedes_the_first(pg, ready):
    """Two live proposals for the same weeks, accepted in either order,
    produce a different program."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    first = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    second = programming.store_draft(
        pg, alice, _draft(title="A different block"),
        program_id=program_id, phase_id=phase_id,
    )
    assert programming.get_draft(pg, alice, first.id).status.value == "stale"
    assert programming.get_draft(pg, alice, second.id).status.value == "draft"


@requires_pg
def test_the_preview_names_every_change(pg, ready):
    """§29.5. "It will update your program" is not something anybody can
    agree to."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    _template(pg, alice, phase_id, name="Upper A")
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    preview = programming.preview_draft(pg, alice, stored.id)

    assert preview.program_id == program_id
    assert preview.program_name == "Test program"
    assert preview.phase_name == "Block 1"
    assert preview.base_revision == 0
    assert preview.resulting_revision == 1
    assert preview.effective_start is not None
    assert preview.weeks_affected == [1]
    change = preview.template_changes[0]
    # The existing session is replaced, not duplicated.
    assert change["action"] == "replace"
    assert change["session"] == "Upper A"
    assert change["exercises"] == ["Barbell Bench Press"]
    assert change["working_sets"] == 4
    assert change["estimated_minutes"] > 0
    # A training draft never moves a nutrition target.
    assert preview.target_changes == []


@requires_pg
def test_accepting_a_draft_versions_and_activates_it(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    template_id = _template(pg, alice, phase_id, name="Upper A")
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    result = programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="read it through; the top set is what bench needs",
    )
    assert result["revision"] == 1
    assert result["templates"][0]["template_id"] == template_id
    assert result["templates"][0]["action"] == "replaced"

    revision = pg.execute(text("""
        SELECT revision, source, draft_id, activated_at, activated_by, notes
        FROM fitness_program_revision WHERE id = :id
    """), {"id": result["program_revision_id"]}).fetchone()
    assert revision.revision == 1
    assert revision.source == "draft"
    assert revision.draft_id == stored.id
    assert revision.activated_at is not None
    assert revision.activated_by == alice
    assert "top set" in revision.notes

    # Both projections carry the draft's prescription.
    rows = pg.execute(text("""
        SELECT exercise_name, target_sets FROM template_exercise
        WHERE template_id = :id
    """), {"id": template_id}).fetchall()
    assert [(row.exercise_name, row.target_sets) for row in rows] == [
        ("Barbell Bench Press", 4),
    ]
    stored_json = pg.execute(text(
        "SELECT exercises, current_revision FROM fitness_template "
        "WHERE id = :id"
    ), {"id": template_id}).fetchone()
    exercises = json.loads(stored_json.exercises) if isinstance(
        stored_json.exercises, str) else stored_json.exercises
    assert exercises[0]["sets"] == 4
    assert stored_json.current_revision == 1

    # The phase records the revision it is running.
    assert pg.execute(text("""
        SELECT program_revision FROM fitness_phase WHERE id = :id
    """), {"id": phase_id}).scalar() == 1


@requires_pg
def test_a_draft_can_introduce_a_session(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    result = programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="there is no upper session yet; this adds one",
    )
    assert result["templates"][0]["action"] == "created"
    created = pg.execute(text("""
        SELECT name, current_revision FROM fitness_template
        WHERE user_id = :u AND phase_id = :phase
    """), {"u": alice, "phase": phase_id}).fetchone()
    assert created.name == "Upper A"
    assert created.current_revision == 1


@requires_pg
def test_a_model_cannot_accept_a_draft(pg, ready):
    """§29.2, in the service and in the database."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    for decider in ("model", "llm", "autonomous", "system"):
        with pytest.raises(programming.ProgrammingError) as excinfo:
            programming.accept_draft(
                pg, alice, stored.id, decided_by=decider,
                reason="this looks like a reasonable block to me",
            )
        assert "a person activates" in str(excinfo.value)

    # And the database refuses it even if a path forgot.
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            UPDATE fitness_program_draft
            SET status = 'accepted', decided_at = NOW(), decided_by = 'model'
            WHERE id = :id
        """), {"id": stored.id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_an_activated_revision_cannot_name_a_model(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_program_revision (
                id, user_id, program_id, revision, snapshot, content_hash,
                source, activated_at, activated_by
            ) VALUES (
                :id, :u, 'p1', 1, '{}'::jsonb, 'h', 'manual', NOW(), 'model'
            )
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_blocking_finding_prevents_activation(pg, ready):
    """§29 completion: no unreviewed model plan is activated."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    bad = _draft(slots=[_unknown_slot()])
    stored = programming.store_draft(
        pg, alice, bad, program_id=program_id, phase_id=phase_id,
    )
    assert not stored.validation.acceptable
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="I want this one anyway, it looks fine",
        )
    assert "blocking finding" in str(excinfo.value)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


def _unknown_slot():
    from app.schemas.fitness_coach import (
        EffortTarget, PrescribedSet, PrescribedSlot, SetRole,
    )

    return PrescribedSlot(
        order=0, exercise_name="Smith Machine Hack Thruster",
        sets=[PrescribedSet(
            index=index, role=SetRole.WORKING, reps_low=5, reps_high=8,
            effort=EffortTarget.RPE, rpe=8.5, rest_seconds=180,
        ) for index in range(4)],
    )


@requires_pg
def test_an_open_question_prevents_activation(pg, two_athletes):
    """A draft with an unanswered question is reviewable, not applicable."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    # No profile: the equipment question fires.
    _library(pg, alice, "Barbell Bench Press", equipment=())
    program_id, phase_id = _program_and_phase(pg, alice)

    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    assert stored.validation.questions
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="going ahead with this block as drafted",
        )
    # A missing constraint is a QUESTION, not a blocking finding: the
    # answer may be "here is my equipment", and refusing the draft outright
    # would make a profile gap require a re-draft. It still cannot be
    # activated while the question stands.
    assert "unanswered" in str(excinfo.value)
    assert "equipment" in str(excinfo.value).lower()
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_acceptance_needs_a_reason(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice, reason="ok",
        )
    assert "needs a reason" in str(excinfo.value)


@requires_pg
def test_a_stale_draft_is_a_conflict_not_a_silent_apply(pg, ready):
    """The plan's "proposal stale revision conflict". A blind retry against
    a changed program is how a reviewed draft gets applied to something
    nobody reviewed."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    # Somebody else versions the program in between.
    pg.execute(text("""
        INSERT INTO fitness_program_revision (
            id, user_id, program_id, revision, snapshot, content_hash,
            source, activated_at, activated_by
        ) VALUES (
            :id, :u, :p, 1, '{}'::jsonb, 'h', 'manual', NOW(), :u
        )
    """), {"id": str(uuid.uuid4()), "u": alice, "p": program_id})
    pg.commit()

    with pytest.raises(programming.RevisionConflict) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="applying the block I reviewed yesterday",
        )
    assert excinfo.value.base == 0
    assert excinfo.value.current == 1
    assert "written for a different program" in str(excinfo.value)


@requires_pg
def test_the_preview_warns_about_a_stale_draft(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    pg.execute(text("""
        INSERT INTO fitness_program_revision (
            id, user_id, program_id, revision, snapshot, content_hash,
            source, activated_at, activated_by
        ) VALUES (
            :id, :u, :p, 1, '{}'::jsonb, 'h', 'manual', NOW(), :u
        )
    """), {"id": str(uuid.uuid4()), "u": alice, "p": program_id})
    pg.commit()
    preview = programming.preview_draft(pg, alice, stored.id)
    assert "revision 0" in preview.warnings[0]


@requires_pg
def test_accepting_twice_is_refused(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="accepted on the first pass",
    )
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="accepting it a second time by accident",
        )
    assert "is accepted" in str(excinfo.value)
    assert "audit trail" in str(excinfo.value)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_a_decided_draft_is_immutable(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="read and accepted this block",
    )
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        pg.execute(text("""
            UPDATE fitness_program_draft SET status = 'rejected'
            WHERE id = :id
        """), {"id": stored.id})
        pg.commit()
    assert "audit trail" in str(excinfo.value)
    pg.rollback()


@requires_pg
def test_a_rejection_keeps_its_reason(pg, ready):
    """The same proposal will be generated again, and "we said no, because
    X" is the only thing that stops it coming back forever."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    programming.reject_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="too much pressing volume for the shoulder right now",
    )
    after = programming.get_draft(pg, alice, stored.id)
    assert after.status.value == "rejected"
    assert "shoulder" in (after.decision_reason or "")
    # The payload is kept, so the proposal is still readable.
    assert after.draft.title == "Four-week upper block"


@requires_pg
def test_a_rejection_needs_a_reason(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    with pytest.raises(programming.ProgrammingError):
        programming.reject_draft(
            pg, alice, stored.id, decided_by=alice, reason="no",
        )


@requires_pg
def test_one_athlete_cannot_see_or_accept_anothers_draft(pg, ready):
    from app.services.fitness import programming

    alice, bob, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    with pytest.raises(LookupError):
        programming.get_draft(pg, bob, stored.id)
    with pytest.raises(LookupError):
        programming.accept_draft(
            pg, bob, stored.id, decided_by=bob,
            reason="accepting somebody else's program draft",
        )
    assert programming.list_drafts(pg, bob) == []


@requires_pg
def test_the_validation_stored_is_the_one_the_reviewer_saw(pg, ready):
    """Recomputing on read would quietly turn a blocked draft into an
    acceptable one because a limitation expired."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(slots=[_unknown_slot()]),
        program_id=program_id, phase_id=phase_id,
    )
    # The exercise appears afterwards. The stored validation does not move.
    _library(pg, alice, "Smith Machine Hack Thruster", equipment=("barbell",))
    reread = programming.get_draft(pg, alice, stored.id)
    assert not reread.validation.acceptable


# ─────────────────────────────────────────────────────────────────────────
# The past does not move (§29.6)
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_activating_a_revision_leaves_logged_sessions_alone(pg, ready):
    """A completed session is a record of what happened. A program edit
    that rewrote it would rewrite history."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    template_id = _template(pg, alice, phase_id, name="Upper A")
    exercise_id = pg.execute(text("""
        SELECT id FROM exercise_library
        WHERE owner_user_id = :u AND name = 'Barbell Bench Press'
    """), {"u": alice}).scalar()

    log_id = str(uuid.uuid4())
    workout_id = _workout(pg, alice, days_ago=3)
    pg.execute(text("""
        INSERT INTO workout_log (
            id, workout_id, user_id, exercise_id, template_id, set_index,
            reps, load_value, load_unit, rpe, session_date, created_at
        ) VALUES (
            :id, :w, :u, :ex, :t, 0, 6, 102.5, 'kg', 8.5,
            CURRENT_DATE - 3, NOW()
        )
    """), {
        "id": log_id, "w": workout_id, "u": alice, "ex": exercise_id,
        "t": template_id,
    })
    pg.commit()
    before = dict(pg.execute(text("""
        SELECT reps, load_value, load_unit, rpe, session_date
        FROM workout_log WHERE id = :id
    """), {"id": log_id}).fetchone()._mapping)

    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="changing the upper session going forward",
    )

    after = dict(pg.execute(text("""
        SELECT reps, load_value, load_unit, rpe, session_date
        FROM workout_log WHERE id = :id
    """), {"id": log_id}).fetchone()._mapping)
    assert after == before


@requires_pg
def test_activating_a_revision_leaves_stored_reviews_alone(pg, ready):
    """A review's input snapshot is what the coach reasoned over. An edit
    to the program must not change what she was looking at."""
    from app.services.fitness import programming
    import hashlib

    alice, _, program_id, phase_id = ready
    _template(pg, alice, phase_id, name="Upper A")
    review_id = str(uuid.uuid4())
    snapshot = {"program": {"phase": {"id": phase_id}}, "note": "as it was"}
    pg.execute(text("""
        INSERT INTO fitness_coach_review (
            id, user_id, kind, status, period_start, period_end,
            input_state, input_hash, state_schema_version,
            analytics_version, collected_at, prompt_version, requested_by,
            revision, attempt, output_schema_version, output, summary,
            created_at, updated_at
        ) VALUES (
            :id, :u, 'weekly', 'complete', CURRENT_DATE - 28, CURRENT_DATE,
            CAST(:state AS JSONB), :hash, 1, 1, NOW(), 'v1', 'user', 1, 1,
            1, '{"summary": "s"}'::jsonb, 's', NOW(), NOW()
        )
    """), {
        "id": review_id, "u": alice, "state": json.dumps(snapshot),
        "hash": hashlib.sha256(review_id.encode()).hexdigest(),
    })
    pg.commit()

    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="changing the block after that review",
    )

    kept = pg.execute(text("""
        SELECT input_state FROM fitness_coach_review WHERE id = :id
    """), {"id": review_id}).scalar()
    kept = json.loads(kept) if isinstance(kept, str) else kept
    assert kept == snapshot


@requires_pg
def test_an_activated_program_revision_is_frozen(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    result = programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="activating this block now",
    )
    for column, value in (
        ("snapshot", "'{\"title\": \"rewritten\"}'::jsonb"),
        ("content_hash", "'deadbeef'"),
        ("revision", "9"),
        ("effect_scope", "'retroactive'"),
    ):
        with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
            pg.execute(text(
                f"UPDATE fitness_program_revision SET {column} = {value} "
                f"WHERE id = :id"
            ), {"id": result["program_revision_id"]})
            pg.commit()
        assert "frozen" in str(excinfo.value)
        pg.rollback()


@requires_pg
def test_a_backdated_revision_states_its_scope(pg, ready):
    """§29.6: a backdated revision requires an explicit effect scope. The
    default is forward, and retroactive has to be asked for."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    result = programming.accept_draft(
        pg, alice, stored.id, decided_by=alice,
        reason="this is how the block actually ran from the 1st",
        effect_scope="retroactive",
        effective_from=date.today() - timedelta(days=14),
    )
    row = pg.execute(text("""
        SELECT effect_scope, effective_from, notes
        FROM fitness_program_revision WHERE id = :id
    """), {"id": result["program_revision_id"]}).fetchone()
    assert row.effect_scope == "retroactive"
    assert row.effective_from == date.today() - timedelta(days=14)
    assert "actually ran" in row.notes


@requires_pg
def test_an_unknown_effect_scope_is_refused(pg, ready):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    stored = programming.store_draft(
        pg, alice, _draft(), program_id=program_id, phase_id=phase_id,
    )
    with pytest.raises(programming.ProgrammingError):
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="applying this block to the whole year somehow",
            effect_scope="everything",
        )


# ─────────────────────────────────────────────────────────────────────────
# Deterministic progression (§29.4)
# ─────────────────────────────────────────────────────────────────────────

def _workout(pg, user_id, *, days_ago=0, title="Session"):
    """A parent `workout` row. `workout_log.workout_id` is NOT NULL, so a
    set without one is not a thing this schema can hold."""
    workout_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, created_at)
        VALUES (:id, :u, :title, NOW() - (:offset || ' days')::interval)
    """), {
        "id": workout_id, "u": user_id, "title": title,
        "offset": str(days_ago),
    })
    pg.commit()
    return workout_id


def _log_session(pg, user_id, exercise_id, *, days_ago, reps, load, rpe=8.0,
                 sets=3, template_id=None):
    workout_id = _workout(pg, user_id, days_ago=days_ago)
    for index in range(sets):
        pg.execute(text("""
            INSERT INTO workout_log (
                id, workout_id, user_id, exercise_id, template_id,
                set_index, reps, load_value, load_unit, rpe, session_date,
                created_at
            ) VALUES (
                :id, :w, :u, :ex, :t, :idx, :reps, :load, 'kg', :rpe,
                CURRENT_DATE - :offset, NOW()
            )
        """), {
            "id": str(uuid.uuid4()), "w": workout_id, "u": user_id,
            "ex": exercise_id, "t": template_id, "idx": index, "reps": reps,
            "load": load, "rpe": rpe, "offset": days_ago,
        })
    pg.commit()


def _slot(name="Barbell Bench Press", *, rule=None, low=5, high=8,
          reference=None, percent=None):
    from app.schemas.fitness_coach import (
        EffortTarget, PrescribedSet, PrescribedSlot, ProgressionRule, SetRole,
    )

    rule = rule or ProgressionRule.DOUBLE
    kwargs = {
        "index": 0, "role": SetRole.WORKING, "rest_seconds": 180,
    }
    if percent is not None:
        kwargs.update({
            "reps": low, "load_percent": percent,
            "effort": EffortTarget.PERCENT_1RM,
        })
    else:
        kwargs.update({
            "reps_low": low, "reps_high": high, "effort": EffortTarget.RPE,
            "rpe": 8.0,
        })
    return PrescribedSlot(
        order=0, exercise_name=name, progression=rule,
        reference_1rm_kg=reference,
        sets=[PrescribedSet(**kwargs)],
    )


@requires_pg
def test_no_history_asks_rather_than_guessing(pg, two_athletes):
    """A suggestion here would be a guess dressed as a plan."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _library(pg, alice, "Barbell Bench Press")
    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "ask"
    assert decision.suggested_load_kg is None
    assert decision.basis_sessions == 0
    assert "guess" in decision.reason


@requires_pg
def test_double_progression_adds_reps_before_load(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    # Six reps against a 5-8 range: inside it, so reps first.
    _log_session(pg, alice, exercise_id, days_ago=3, reps=6, load=100.0,
                 rpe=8.0)

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "advance_reps"
    assert decision.suggested_load_kg == 100.0
    assert decision.suggested_reps == 7
    assert "before adding weight" in decision.reason


@requires_pg
def test_double_progression_adds_load_at_the_top_of_the_range(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=8.0)

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "advance_load"
    # Upper body: 2.5kg, rounded to the nearest 1.25.
    assert decision.suggested_load_kg == 102.5
    assert decision.suggested_reps == 5


@requires_pg
def test_a_lower_body_lift_gets_the_bigger_jump(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Back Squat")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=140.0,
                 rpe=7.5)

    decision = programming.progression_for(
        pg, alice, _slot("Back Squat"),
    )
    assert decision.action == "advance_load"
    assert decision.suggested_load_kg == 145.0


@requires_pg
def test_a_hard_session_holds_rather_than_advancing(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=9.5)

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "advance_reps"
    assert decision.suggested_load_kg == 100.0


@requires_pg
def test_linear_progression_adds_a_fixed_increment(pg, two_athletes):
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=5, load=100.0,
                 rpe=7.0)

    decision = programming.progression_for(
        pg, alice, _slot(rule=ProgressionRule.LINEAR),
    )
    assert decision.action == "advance_load"
    assert decision.suggested_load_kg == 102.5
    assert "Linear" in decision.reason


@requires_pg
def test_linear_progression_holds_when_the_floor_was_missed(pg, two_athletes):
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=3, load=100.0,
                 rpe=9.0)

    decision = programming.progression_for(
        pg, alice, _slot(rule=ProgressionRule.LINEAR),
    )
    assert decision.action == "hold"
    assert decision.suggested_load_kg == 100.0
    assert "5-rep floor" in decision.reason


@requires_pg
def test_percentage_progression_reads_the_plan_not_last_week(pg, two_athletes):
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=5, load=90.0)

    decision = programming.progression_for(
        pg, alice,
        _slot(rule=ProgressionRule.PERCENTAGE, reference=120.0, percent=80.0),
    )
    assert decision.action == "advance_load"
    assert decision.suggested_load_kg == 96.25
    assert "reference" in decision.reason


@requires_pg
def test_percentage_progression_with_no_reference_asks(pg, two_athletes):
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=5, load=90.0)

    decision = programming.progression_for(
        pg, alice,
        # MANUAL, because the typed shape refuses PERCENTAGE with no
        # reference; the rule still has to answer honestly.
        _slot(rule=ProgressionRule.PERCENTAGE, percent=None),
    )
    assert decision.action in ("ask", "advance_reps", "advance_load", "hold")


@requires_pg
def test_manual_progression_holds_and_says_so(pg, two_athletes):
    from app.schemas.fitness_coach import ProgressionRule
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=6.0)

    decision = programming.progression_for(
        pg, alice, _slot(rule=ProgressionRule.MANUAL),
    )
    assert decision.action == "hold"
    assert "leaving the call to you" in decision.reason


@requires_pg
def test_poor_recovery_holds_instead_of_advancing(pg, two_athletes):
    """Recovery never inflates a jump — at most it downgrades an advance to
    a hold. That is `progressive_overload`'s existing rule and this keeps
    it."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=7.0)
    pg.execute(text("""
        INSERT INTO daily_recovery_log (
            id, user_id, log_date, sleep_hours, soreness_level, created_at
        ) VALUES (:id, :u, CURRENT_DATE, 4.5, 8, NOW())
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "hold"
    assert decision.recovery_override
    assert "soreness" in decision.recovery_override


@requires_pg
def test_good_recovery_does_not_inflate_the_jump(pg, two_athletes):
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=7.0)
    pg.execute(text("""
        INSERT INTO daily_recovery_log (
            id, user_id, log_date, sleep_hours, soreness_level, hrv,
            created_at
        ) VALUES (:id, :u, CURRENT_DATE, 9.0, 1, 85, NOW())
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    decision = programming.progression_for(pg, alice, _slot())
    # The same +2.5kg as ordinary recovery, not more.
    assert decision.suggested_load_kg == 102.5


@requires_pg
def test_reported_pain_reduces_the_load(pg, two_athletes):
    """§29.4: recovery/pain can propose holding, reducing or deloading."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=7.0)
    pg.execute(text("""
        INSERT INTO fitness_pain_report (
            id, user_id, occurred_at, logical_date, pain_present, severity,
            location, source, created_at
        ) VALUES (
            :id, :u, NOW() - INTERVAL '2 days', CURRENT_DATE - 2, TRUE, 7,
            'left shoulder', 'user', NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "reduce"
    assert decision.suggested_load_kg == 90.0
    assert "pain reported at 7/10" in decision.reason


@requires_pg
def test_old_pain_does_not_hold_a_lift_forever(pg, two_athletes):
    """A report from three weeks ago that was never followed up must not
    gate load indefinitely — that is the self-reinforcing nag shape."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=7.0)
    pg.execute(text("""
        INSERT INTO fitness_pain_report (
            id, user_id, occurred_at, logical_date, pain_present, severity,
            location, source, created_at
        ) VALUES (
            :id, :u, NOW() - INTERVAL '30 days', CURRENT_DATE - 30, TRUE, 8,
            'left shoulder', 'user', NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "advance_load"


@requires_pg
def test_a_scheduled_deload_wins_over_good_recovery(pg, two_athletes):
    """The phase says this week is a deload. A good night's sleep does not
    override the plan."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = _library(pg, alice, "Barbell Bench Press")
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=100.0,
                 rpe=6.5)
    pg.execute(text("""
        INSERT INTO fitness_phase (
            id, user_id, name, start_date, end_date, status, deload_week,
            created_at
        ) VALUES (
            :id, :u, 'Deload block', CURRENT_DATE, CURRENT_DATE + 7,
            'active', 1, CURRENT_TIMESTAMP
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    decision = programming.progression_for(pg, alice, _slot())
    assert decision.action == "deload"
    assert decision.suggested_load_kg == 60.0
    assert "scheduled deload" in decision.reason


@requires_pg
def test_an_assisted_lifts_help_is_not_read_as_load(pg, two_athletes):
    """`effective_load` is the one implementation of "comparable", and this
    is why: an assisted pull-up logged at 30 is 30kg of HELP."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    exercise_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO exercise_library (
            id, name, normalized_name, movement_pattern, muscle_groups,
            equipment_required, injury_contraindications, owner_user_id,
            visibility, load_convention, created_at, updated_at
        ) VALUES (
            :id, 'Assisted Pull-Up', 'assisted pull-up', 'vertical_pull',
            '["back"]'::jsonb, '["machine"]'::jsonb, '[]'::jsonb, :u,
            'private', 'assisted', NOW(), NOW()
        )
    """), {"id": exercise_id, "u": alice})
    pg.commit()
    _log_session(pg, alice, exercise_id, days_ago=3, reps=8, load=30.0,
                 rpe=7.0)

    decision = programming.progression_for(
        pg, alice, _slot("Assisted Pull-Up"),
    )
    # Whatever it decides, it must not suggest 32.5 — that would be MORE
    # assistance presented as progress.
    assert decision.suggested_load_kg != 32.5


# ─────────────────────────────────────────────────────────────────────────
# Draft generation: the model cannot activate
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_generator_stores_a_draft_and_touches_no_template(
    pg, ready, monkeypatch,
):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    template_id = _template(pg, alice, phase_id, name="Upper A")
    before = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :id"
    ), {"id": template_id}).scalar()

    payload = _draft().model_dump(mode="json")

    async def fake_chat(system, user):
        # The allowed-exercise list reaches the prompt, and the owner id
        # does not.
        assert "Barbell Bench Press" in user
        assert alice not in user
        return json.dumps(payload), "qwen3.8-27b"

    monkeypatch.setattr(programming, "_chat", fake_chat)
    stored = asyncio.run(programming.generate_draft(
        pg, alice, request="next block", program_id=program_id,
        phase_id=phase_id,
    ))
    assert stored.status.value == "draft"
    assert stored.model_actual == "qwen3.8-27b"

    after = pg.execute(text(
        "SELECT exercises FROM fitness_template WHERE id = :id"
    ), {"id": template_id}).scalar()
    assert after == before
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_prose_instead_of_json_gets_one_repair_then_fails(
    pg, ready, monkeypatch,
):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    calls = []

    async def fake_chat(system, user):
        calls.append(user)
        return "Here is a great four-week block for you…", "qwen3.8-27b"

    monkeypatch.setattr(programming, "_chat", fake_chat)
    with pytest.raises(programming.ProgrammingError) as excinfo:
        asyncio.run(programming.generate_draft(
            pg, alice, program_id=program_id, phase_id=phase_id,
        ))
    assert len(calls) == 2, "the repair budget is one turn"
    assert "rejected" in calls[1]
    assert "not produce a usable draft" in str(excinfo.value)


@requires_pg
def test_an_invented_field_is_rejected(pg, ready, monkeypatch):
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    payload = _draft().model_dump(mode="json")
    payload["activate_now"] = True

    async def fake_chat(system, user):
        return json.dumps(payload), "qwen3.8-27b"

    monkeypatch.setattr(programming, "_chat", fake_chat)
    with pytest.raises(programming.ProgrammingError):
        asyncio.run(programming.generate_draft(
            pg, alice, program_id=program_id, phase_id=phase_id,
        ))


@requires_pg
def test_the_prompt_carries_no_diagnosis(pg, ready, monkeypatch):
    """§29.3. The model is told WHICH exercises to avoid, not what is wrong
    with the athlete — a model that never receives a diagnosis cannot
    repeat one."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation (
            id, user_id, area, description, excluded_exercise_ids,
            modified_exercise_ids, severity_flag, effective_from, status,
            created_at, updated_at
        ) VALUES (
            :id, :u, 'shoulder', 'left shoulder, no heavy overhead',
            '[]'::jsonb, '[]'::jsonb, 'moderate', CURRENT_DATE - 10,
            'active', NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    seen = {}

    async def fake_chat(system, user):
        seen["system"] = system
        seen["user"] = user
        return json.dumps(_draft().model_dump(mode="json")), "qwen"

    monkeypatch.setattr(programming, "_chat", fake_chat)
    asyncio.run(programming.generate_draft(
        pg, alice, program_id=program_id, phase_id=phase_id,
    ))
    assert "shoulder" in seen["user"]
    assert "do not interpret them" in seen["system"].lower()
    assert "not an mri" in seen["system"].lower()


@requires_pg
def test_the_allowed_list_excludes_unavailable_equipment(pg, ready):
    """The cheap half of §29.3: a name that was never offered cannot be
    prescribed."""
    from app.services.fitness import programming

    alice, _, _, _ = ready
    _library(pg, alice, "Leg Press", equipment=("leg press machine",))
    constraints = programming.load_constraints(pg, alice)
    names = programming.allowed_exercises(pg, alice, constraints)
    assert "Barbell Bench Press" in names
    assert "Leg Press" not in names


@requires_pg
def test_the_performance_summary_is_computed_not_narrated(pg, ready):
    """§29.2: deterministic performance data. A model asked to read its own
    inputs reads them wrong, and the error is invisible because the output
    is prose."""
    from app.services.fitness import programming

    alice, _, _, _ = ready
    exercise_id = pg.execute(text("""
        SELECT id FROM exercise_library
        WHERE owner_user_id = :u AND name = 'Barbell Bench Press'
    """), {"u": alice}).scalar()
    _log_session(pg, alice, exercise_id, days_ago=3, reps=6, load=100.0,
                 rpe=8.0)

    summary = programming.performance_summary(
        pg, alice, ["Barbell Bench Press"],
    )
    entry = summary["Barbell Bench Press"][0]
    assert entry["min_reps"] == 6
    assert entry["mean_load"] == 100.0
    assert entry["unit"] == "kg"
    assert entry["mean_rpe"] == 8.0


# ─────────────────────────────────────────────────────────────────────────
# The remaining cases the plan names
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_question_is_not_blocking_but_still_stops_activation(pg, ready):
    """The distinction `DraftFinding` exists to carry.

    "This draft cannot be applied" and "this needs an answer first" are
    refused for different reasons. Collapsing them would either block on a
    note or activate past a real conflict — and a validator where every
    question is also blocking makes a profile gap require a re-draft rather
    than a sentence.
    """
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    # A session on a day that is not on the available list: a question.
    from app.schemas.fitness_coach import PrescribedSession

    base = _draft()
    sunday = PrescribedSession(
        name="Upper A", day_of_week=6, scheduled_days=["sunday"],
        slots=base.weeks[0].sessions[0].slots,
    )
    stored = programming.store_draft(
        pg, alice, _draft(sessions=[sunday]),
        program_id=program_id, phase_id=phase_id,
    )
    assert stored.validation.blocking == []
    assert stored.validation.questions
    # ...and `acceptable` agrees with the server, rather than the UI saying
    # yes about a row the server will refuse.
    assert stored.validation.acceptable is False
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.accept_draft(
            pg, alice, stored.id, decided_by=alice,
            reason="running this on sunday is fine by me",
        )
    assert "unanswered" in str(excinfo.value)
    assert DraftValidationCode.MISSING_CONSTRAINT in {
        one.code for one in stored.validation.findings
    }


@requires_pg
def test_a_draft_can_serve_several_goals(pg, ready):
    """The plan's "multiple goals". Two active goals is the normal case —
    get stronger and lose fat — and a draft that could only name one would
    report half its own purpose.
    """
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    # 'cut', not 'body_composition': `ck_athlete_goal_kind` is a closed
    # set, and a second primary goal needs `is_primary` off.
    _goal(pg, alice, kind="cut",
          rationale="lose 4kg without losing the bench", primary=False)

    constraints = programming.load_constraints(pg, alice)
    assert len(constraints.goals) == 2

    draft = _draft(addresses_goals=[
        "add 10kg to the bench", "lose 4kg without losing the bench",
    ])
    stored = programming.store_draft(
        pg, alice, draft, program_id=program_id, phase_id=phase_id,
    )
    assert stored.validation.acceptable, [
        one.message for one in stored.validation.findings
    ]
    assert len(stored.draft.addresses_goals) == 2
    # And the goals reach the model's constraints payload.
    payload = programming.constraints_payload(constraints)
    assert len(payload["goals"]) == 2


@requires_pg
def test_an_imported_plan_still_reads_and_writes(pg, two_athletes):
    """The plan's "import/retry compatibility", and the completion
    criterion that existing imported plans keep working.

    `plan_importer` writes `fitness_template.exercises` directly and knows
    nothing about revisions. Its output has to stay readable by the typed
    parser and writable by the one writer, or Step 29 breaks every plan
    somebody imported.
    """
    from app.services.fitness import programming
    from app.services.plan_importer import apply_imported_plan, _normalize

    alice, _ = two_athletes
    parsed = _normalize({
        "program": {"name": "Imported block", "goal": "strength",
                    "duration_weeks": 4},
        "phases": [{"name": "Phase 1", "duration_weeks": 4}],
        "templates": [{
            "name": "Push A",
            "scheduled_days": ["monday"],
            "exercises": [
                {"name": "Barbell Bench Press", "sets": 4, "reps": "5-8",
                 "rpe": 8, "rest_seconds": 180},
                {"name": "Overhead Press", "sets": 3, "reps": "8-10"},
            ],
        }],
    })
    result = apply_imported_plan(pg, alice, parsed)
    pg.commit()

    template_id = pg.execute(text("""
        SELECT id FROM fitness_template WHERE user_id = :u AND name = 'Push A'
    """), {"u": alice}).scalar()
    assert template_id, result

    # It parses.
    session = programming.read_session(pg, alice, template_id)
    assert [slot.exercise_name for slot in session.slots] == [
        "Barbell Bench Press", "Overhead Press",
    ]
    assert session.slots[0].working_sets == 4

    # And it writes, producing revision 1 on a template that had none.
    revision = programming.write_session(pg, alice, template_id, session)
    assert revision == 1
    rows = pg.execute(text("""
        SELECT exercise_name FROM template_exercise
        WHERE template_id = :id ORDER BY order_index
    """), {"id": template_id}).fetchall()
    assert [row.exercise_name for row in rows] == [
        "Barbell Bench Press", "Overhead Press",
    ]


@requires_pg
def test_a_two_a_day_keeps_both_sessions(pg, two_athletes):
    """The completion criterion names two-a-day plans specifically, and
    this codebase has already shipped readers that broke on the first
    match — the PM session simply vanished. Two sessions on one day are two
    sessions."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    morning = _template(pg, alice, phase_id, name="Monday AM",
                        scheduled=("monday",))
    evening = _template(pg, alice, phase_id, name="Monday PM",
                        scheduled=("monday",))

    for template_id in (morning, evening):
        session = programming.read_session(pg, alice, template_id)
        programming.write_session(pg, alice, template_id, session)

    names = [
        row.name for row in pg.execute(text("""
            SELECT t.name FROM fitness_template t
            WHERE t.user_id = :u AND t.phase_id = :phase
              AND t.current_revision = 1
            ORDER BY t.name
        """), {"u": alice, "phase": phase_id}).fetchall()
    ]
    assert names == ["Monday AM", "Monday PM"]
    revisions = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_template_revision WHERE user_id = :u
    """), {"u": alice}).scalar()
    assert revisions == 2


@requires_pg
def test_a_template_with_an_unnameable_exercise_does_not_break_the_session(
    pg, two_athletes,
):
    """Older imported data holds exercises with no name. One bad row must
    not make the whole template unreadable — the rest of the prescription
    is still the plan."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id, exercises=[
        {"sets": 3, "reps": "8-10"},
        {"name": "Barbell Row", "sets": 3, "reps": "8-12"},
    ])
    session = programming.read_session(pg, alice, template_id)
    assert [slot.exercise_name for slot in session.slots] == ["Barbell Row"]


@requires_pg
def test_a_template_with_no_usable_exercise_refuses_rather_than_emptying(
    pg, two_athletes,
):
    """An empty typed session would write an empty template, which is a
    silent deletion of somebody's programming."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _, phase_id = _program_and_phase(pg, alice)
    template_id = _template(pg, alice, phase_id, exercises=[{"sets": 3}])
    with pytest.raises(programming.ProgrammingError) as excinfo:
        programming.read_session(pg, alice, template_id)
    assert "no usable exercises" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────
# What the live roundtrip taught (2026-10-02)
# ─────────────────────────────────────────────────────────────────────────

def test_the_output_cap_fits_a_measured_week():
    """`scripts/fitness_draft_smoke.py` against the deployed 27B measured
    one week — three sessions, thirteen slots, thirty-four working sets — at
    ~3,970 output tokens in 196.7s.

    Both constants were originally below that, so every live draft failed:
    the cap truncated the JSON and the timeout fired before anything came
    back. A stub cannot catch either, which is why the live run exists.
    """
    from app.prompts import fitness_program_draft as prompts
    from app.services.fitness.programming import DRAFT_TIMEOUT_SECONDS

    measured_tokens = 3970
    measured_seconds = 197

    assert prompts.MAX_OUTPUT_TOKENS > measured_tokens, (
        "the output cap is below a measured single week; the draft will "
        "truncate mid-object and parse as nothing"
    )
    assert DRAFT_TIMEOUT_SECONDS > measured_seconds * 1.5, (
        "the timeout leaves no headroom over a measured single week"
    )
    # And the wait must not be tighter than the client's own budget, or the
    # client's timeout can never apply — which is what 180s did.
    from app.core.config import settings
    assert DRAFT_TIMEOUT_SECONDS < settings.bg_llm_request_timeout


def test_a_truncated_draft_names_the_budget_not_the_prompt():
    """A draft cut off at the cap is not malformed JSON.

    Reporting it as "the output was not JSON" sends the next reader to the
    prompt instead of to the budget, and the remedy is different: a smaller
    ask or a bigger cap, not better wording.
    """
    import asyncio

    from app.services.fitness import programming

    async def truncating_client(*args, **kwargs):
        return {
            "model": "qwen3.8-27b",
            "choices": [{
                "message": {"content": '{"kind": "week", "title": "Week 1'},
                "finish_reason": "length",
            }],
        }

    class _Client:
        chat_completion = staticmethod(truncating_client)

    import app.core.llm as llm_module
    original = llm_module.get_background_llm_client
    llm_module.get_background_llm_client = lambda: _Client()
    try:
        with pytest.raises(programming.TruncatedDraft) as excinfo:
            asyncio.run(programming._chat("system", "user"))
    finally:
        llm_module.get_background_llm_client = original

    message = str(excinfo.value)
    assert "output cap" in message
    assert "multi-week block does not fit" in message
    # It names both knobs, because raising one without the other just moves
    # the failure from truncation to timeout.
    assert "MAX_OUTPUT_TOKENS" in message
    assert "DRAFT_TIMEOUT_SECONDS" in message


def test_a_truncated_draft_is_not_repaired(pg, ready, monkeypatch):
    """The repair prompt is LONGER than the original, so retrying a draft
    that already ran out of budget spends another three minutes to fail the
    same way."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    calls = []

    async def truncating(system, user, **kwargs):
        calls.append(user)
        raise programming.TruncatedDraft("the model hit the 7000-token cap")

    monkeypatch.setattr(programming, "_chat", truncating)
    with pytest.raises(programming.TruncatedDraft):
        asyncio.run(programming.generate_draft(
            pg, alice, program_id=program_id, phase_id=phase_id,
        ))
    assert len(calls) == 1, "a truncated draft spent the repair turn"


@requires_pg
def test_the_offered_list_never_includes_unavailable_equipment(pg, ready):
    """The live run's one blocking finding was the smoke script's fault, not
    the model's: it offered all twenty exercises while production filters by
    equipment first. The model picked a leg extension it had been handed.

    This is the property that made that a fixture bug rather than a real
    one, so it is worth pinning: an exercise the athlete cannot perform is
    never offered, and the validator's equipment rule is the backstop for a
    name the model invented rather than the first line of defence.
    """
    from app.services.fitness import programming

    alice, _, _, _ = ready
    _library(pg, alice, "Leg Extension", equipment=("leg extension machine",))
    constraints = programming.load_constraints(pg, alice)
    offered = programming.allowed_exercises(pg, alice, constraints)

    assert "Leg Extension" not in offered
    assert "Barbell Bench Press" in offered
    for name in offered:
        row = pg.execute(text("""
            SELECT equipment_required FROM exercise_library
            WHERE name = :name AND owner_user_id = :u
        """), {"name": name, "u": alice}).fetchone()
        if row is None or not row.equipment_required:
            continue
        required = {
            str(item).strip().lower()
            for item in json.loads(row.equipment_required)
            if item
        } if isinstance(row.equipment_required, str) else {
            str(item).strip().lower() for item in row.equipment_required
        }
        assert not (required - constraints.equipment), name


@requires_pg
def test_a_contraindicated_exercise_is_never_offered(pg, two_athletes):
    """The 2026-10-02 live run's real finding.

    An Overhead Press was offered to an athlete with a recorded shoulder
    limitation, the model used it, and `validate_draft` blocked the entire
    draft for using what it had been handed. The offered list and the
    validator must not disagree: the validator is the backstop for a name
    the model INVENTED, or for a limitation recorded after the draft — not
    the first line of defence.
    """
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Row", equipment=("barbell",))
    _library(pg, alice, "Overhead Press", equipment=("barbell", "rack"),
             contraindications=("shoulder",))
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation (
            id, user_id, area, description, excluded_exercise_ids,
            modified_exercise_ids, severity_flag, effective_from, status,
            created_at, updated_at
        ) VALUES (
            :id, :u, 'shoulder', 'left shoulder on heavy pressing',
            '[]'::jsonb, '[]'::jsonb, 'moderate', CURRENT_DATE - 10,
            'active', NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    constraints = programming.load_constraints(pg, alice)
    offered = programming.allowed_exercises(pg, alice, constraints)
    assert "Overhead Press" not in offered
    assert "Barbell Row" in offered


@requires_pg
def test_a_contraindicated_exercise_is_still_blocked_if_it_appears(
    pg, two_athletes,
):
    """Withholding it from the list does not retire the validator rule: a
    draft can name an exercise it was never offered, and a limitation can
    be recorded after the draft was written."""
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press", equipment=("barbell", "bench"),
             contraindications=("shoulder",))
    pg.execute(text("""
        INSERT INTO fitness_athlete_limitation (
            id, user_id, area, description, excluded_exercise_ids,
            modified_exercise_ids, severity_flag, effective_from, status,
            created_at, updated_at
        ) VALUES (
            :id, :u, 'shoulder', 'left shoulder on heavy pressing',
            '[]'::jsonb, '[]'::jsonb, 'moderate', CURRENT_DATE - 10,
            'active', NOW(), NOW()
        )
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    validation = programming.validate_draft(pg, alice, _draft())
    assert DraftValidationCode.LIMITATION_CONFLICT in {
        one.code for one in validation.blocking
    }


@requires_pg
def test_a_diagnosis_in_the_drafts_prose_is_refused(pg, two_athletes):
    """§29.3 enforced rather than requested.

    Until the 2026-10-02 live run the draft path never called `safety` at
    all: the prompt said "you are reading a list, not an MRI" and nothing
    checked. The schema has no field for a diagnosis, so prose is the only
    place one can appear.
    """
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press", equipment=("barbell", "bench"))

    diagnosing = _draft(
        rationale=(
            "The left shoulder pain is impingement, so this block works "
            "around it."
        ),
    )
    validation = programming.validate_draft(pg, alice, diagnosing)
    blocking = [
        one for one in validation.blocking
        if one.code is DraftValidationCode.DIAGNOSTIC_LANGUAGE
    ]
    assert blocking
    assert "names a condition" in blocking[0].message
    assert blocking[0].path == "rationale"


@requires_pg
def test_treatment_advice_in_a_slot_note_is_refused(pg, two_athletes):
    """Every free-text field is covered, not just the top-level ones — a
    set note is as publishable as a rationale."""
    from app.schemas.fitness_coach import (
        DraftValidationCode, EffortTarget, PrescribedSet, PrescribedSlot,
        SetRole,
    )
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press", equipment=("barbell", "bench"))

    slot = PrescribedSlot(
        order=0, exercise_name="Barbell Bench Press",
        note="Take 400 mg ibuprofen beforehand if the shoulder is sore.",
        sets=[PrescribedSet(
            index=index, role=SetRole.WORKING, reps_low=5, reps_high=8,
            effort=EffortTarget.RPE, rpe=8.5, rest_seconds=180,
        ) for index in range(4)],
    )
    validation = programming.validate_draft(pg, alice, _draft(slots=[slot]))
    blocking = [
        one for one in validation.blocking
        if one.code is DraftValidationCode.DIAGNOSTIC_LANGUAGE
    ]
    assert blocking
    assert "slots[0].note" in blocking[0].path


@requires_pg
def test_ordinary_shoulder_care_language_still_passes(pg, two_athletes):
    """The distinction that matters, and the one my first smoke script got
    wrong: "face pulls for rotator cuff health" is gym language, and
    `DIAGNOSIS_TERMS` holds "rotator cuff tear" — the condition — not the
    anatomy. A check that fires on this is an outage, exactly like the
    `"take a"` substring was."""
    from app.schemas.fitness_coach import DraftValidationCode
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    _library(pg, alice, "Barbell Bench Press", equipment=("barbell", "bench"))

    careful = _draft(
        rationale=(
            "Bench has stalled, so this adds incline volume and face pulls "
            "to support rotator cuff health and keep the shoulder quiet."
        ),
        limitations_respected=[
            "Kept heavy flat pressing out of the top set to reduce shoulder "
            "stress.",
        ],
    )
    validation = programming.validate_draft(pg, alice, careful)
    assert DraftValidationCode.DIAGNOSTIC_LANGUAGE not in {
        one.code for one in validation.findings
    }


def test_the_prompt_shows_how_to_express_a_hold():
    """The live model expressed a 45-second plank as `reps_low: 45,
    reps_high: 60`, because the shape block only ever showed a rep set. The
    schema has supported `metric: "time"` all along; the prompt simply
    never said so."""
    from app.prompts import fitness_program_draft as prompts

    assert '"metric": "time"' in prompts.SYSTEM_PROMPT
    assert '"seconds": 45' in prompts.SYSTEM_PROMPT
    lowered = prompts.SYSTEM_PROMPT.lower()
    assert "a plank is 45 seconds, not 45 reps" in lowered


@requires_pg
def test_a_clinical_leak_is_repaired_once_then_refused(pg, ready, monkeypatch):
    """The 2026-10-02 live run's most important finding.

    With the contraindicated exercises withheld, the model had to explain
    WHY it was avoiding something and invented a condition: the athlete's
    note says "left shoulder complains on heavy flat pressing" and the
    draft said "to avoid aggravating shoulder impingement".

    The review path's rule applies verbatim — a sentence containing a
    diagnosis cannot be repaired by deleting a word — so the draft is NOT
    stored. A warning beside a diagnosis is still a diagnosis.
    """
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    leaking = _draft(
        rationale=(
            "Excluded the overhead press to avoid aggravating shoulder "
            "impingement."
        ),
    ).model_dump(mode="json")

    calls = []

    async def always_leaks(system, user, **kwargs):
        calls.append(user)
        return json.dumps(leaking), "qwen3.8-27b"

    monkeypatch.setattr(programming, "_chat", always_leaks)
    with pytest.raises(programming.ProgrammingError) as excinfo:
        asyncio.run(programming.generate_draft(
            pg, alice, program_id=program_id, phase_id=phase_id,
        ))

    assert len(calls) == 2, "the clinical leak got exactly one repair turn"
    assert "said so again after being told not to" in str(excinfo.value)
    # And nothing was stored: an invented diagnosis must not reach the
    # database or a screen.
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_program_draft WHERE user_id = :u
    """), {"u": alice}).scalar() == 0

    # The repair turn told it to remove the name rather than soften it.
    assert "REMOVE the name" in calls[1]
    assert "no acceptable way to phrase one" in calls[1]


@requires_pg
def test_a_repaired_draft_is_stored(pg, ready, monkeypatch):
    """The repair has to be able to succeed, or the gate is just an outage."""
    from app.services.fitness import programming

    alice, _, program_id, phase_id = ready
    leaking = _draft(
        rationale="Excluded the press to avoid aggravating impingement.",
    ).model_dump(mode="json")
    clean = _draft(
        rationale=(
            "Excluded the overhead press because of the recorded shoulder "
            "limitation."
        ),
    ).model_dump(mode="json")

    answers = [leaking, clean]

    async def leaks_then_complies(system, user, **kwargs):
        return json.dumps(answers.pop(0)), "qwen3.8-27b"

    monkeypatch.setattr(programming, "_chat", leaks_then_complies)
    stored = asyncio.run(programming.generate_draft(
        pg, alice, program_id=program_id, phase_id=phase_id,
    ))
    assert "impingement" not in stored.draft.rationale
    assert stored.validation.acceptable, [
        one.message for one in stored.validation.findings
    ]


@requires_pg
def test_performance_history_is_scoped_to_what_may_be_prescribed(
    pg, two_athletes,
):
    """The live run said it out loud: "Overhead Press (not in allowed list
    but noted in recent performance)". History for a lift the model cannot
    prescribe is an invitation to prescribe it — the same landmine as
    offering the exercise, one wrapper over."""
    from app.services.fitness import programming

    alice, _ = two_athletes
    _profile(pg, alice)
    _goal(pg, alice)
    bench = _library(pg, alice, "Barbell Bench Press",
                     equipment=("barbell", "bench"))
    press = _library(pg, alice, "Leg Press",
                     equipment=("leg press machine",))
    _log_session(pg, alice, bench, days_ago=3, reps=6, load=100.0)
    _log_session(pg, alice, press, days_ago=4, reps=10, load=180.0)

    constraints = programming.load_constraints(pg, alice)
    offered = programming.allowed_exercises(pg, alice, constraints)
    assert "Leg Press" not in offered

    scoped = programming.performance_summary(
        pg, alice, [one for one in ["Barbell Bench Press", "Leg Press"]
                    if one in set(offered)],
    )
    assert "Barbell Bench Press" in scoped
    assert "Leg Press" not in scoped
