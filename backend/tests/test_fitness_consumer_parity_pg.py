"""Step 18 of FITNESS_COACH_IMPLEMENTATION_PLAN: Sara's fitness surfaces no
longer contradict each other.

Before this, five readers each did their own arithmetic over the same tables:

* `fitness_context.py` summed `food_log` by `DATE(logged_at)` in ET;
  `tools/fitness/summary.py` summed it by `DATE(created_at)` in **UTC**. Two
  different days, two different totals, in the same chat turn.
* `health_consolidation/data_collector.py` set `workouts_count =
  len(set_rows)` — one session of 24 sets told the weekly prompt David
  trained 24 times.
* three readers computed volume as `SUM(weight * reps)` over the legacy
  integer column, so a 102.5 kg squat counted as 102, a 40 kg dumbbell press
  counted one hand, and an assisted pull-up counted the assistance as work.
* `data_collector` dropped a body weight whose unit was `kg` instead of
  converting it, so a kg-logging week reported no weight data at all.

Each of those is a test below. The point is not that the new numbers are
prettier — it is that there is now one place they come from, so a fix lands
everywhere at once.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_consumer_parity_pg.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
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
    uid = f"s18-{uuid.uuid4().hex[:18]}"
    pg.execute(text("""
        INSERT INTO app_user (id, email, password_hash, created_at)
        VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
    """), {"id": uid, "e": f"{uid}@s18.invalid", "p": unusable_hash})
    pg.execute(text("""
        INSERT INTO fitness_athlete_profile (id, user_id, timezone, created_at, updated_at)
        VALUES (:i, :u, 'America/New_York', NOW(), NOW())
        ON CONFLICT (user_id) DO NOTHING
    """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield uid
    pg.rollback()
    for table in ("workout_log", "workout", "workout_session", "food_log",
                  "daily_recovery_log", "health_metric", "weight_trend",
                  "fitness_target_revision", "fitness_athlete_profile",
                  "fitness_phase", "fitness_program", "fitness_goals",
                  "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [uid]})
        except Exception:
            pg.rollback()
    # exercise_library's owner column is `owner_user_id`, not `user_id`.
    try:
        pg.execute(text("""
            DELETE FROM exercise_alias WHERE exercise_library_id IN (
                SELECT id FROM exercise_library WHERE owner_user_id = :u
            )
        """), {"u": uid})
        pg.execute(text(
            "DELETE FROM exercise_library WHERE owner_user_id = :u"
        ), {"u": uid})
    except Exception:
        pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


def _today(pg, athlete) -> date:
    from app.services.fitness.consumers import athlete_local_today
    return athlete_local_today(pg, athlete)


def _meal(pg, athlete, *, day: date, hour: int, calories, protein=None,
          carbs=None, fats=None, created_offset_hours: int = 0, name="chicken"):
    """A meal, with `logged_at` and `created_at` deliberately disagreeing.

    `logged_at` is naive ET wall-clock; `created_at` is naive UTC. For an
    evening meal the two land on different calendar days, which is exactly
    the case that made the two readers disagree.
    """
    logged_at = datetime(day.year, day.month, day.day, hour, 0)
    created_at = logged_at + timedelta(hours=4 + created_offset_hours)
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, protein, carbs, fats,
             logged_at, created_at, updated_at)
        VALUES (:id, :u, 'dinner', CAST(:fi AS jsonb), :cal, :pro, :car, :fat,
                :logged, :created, :created)
    """), {
        "id": str(uuid.uuid4()), "u": athlete,
        "fi": json.dumps([{"name": name, "quantity": 1, "unit": "serving"}]),
        "cal": calories, "pro": protein, "car": carbs, "fat": fats,
        "logged": logged_at, "created": created_at,
    })
    pg.commit()


def _exercise(pg, athlete, name, *, convention="total"):
    """A private exercise through the service, so visibility and the owner
    constraint (revision 159) are satisfied the way production satisfies them.

    `convention=None` is the case the analytics must refuse rather than
    assume: an exercise whose load convention was never recorded. The service
    will not create one, so that row is written directly.
    """
    if convention is None:
        eid = str(uuid.uuid4())
        pg.execute(text("""
            INSERT INTO exercise_library
                (id, name, normalized_name, movement_pattern, owner_user_id,
                 visibility, load_convention, created_at)
            VALUES (:id, :n, :nn, 'other', :u, 'private', NULL, NOW())
        """), {"id": eid, "n": name, "nn": name.lower().replace(" ", "_"),
               "u": athlete})
        pg.commit()
        return eid

    from app.services.fitness.exercises import create_custom_exercise
    ref = create_custom_exercise(pg, athlete, name, load_convention=convention)
    pg.commit()
    return ref.id


def _set(pg, athlete, *, day: date, exercise_id, exercise_name, reps, load,
         load_unit="lb", set_kind="working", rpe=None, workout_id=None):
    if workout_id is None:
        workout_id = str(uuid.uuid4())
        pg.execute(text("""
            INSERT INTO workout (id, user_id, title, status, created_at)
            VALUES (:id, :u, 'Session', 'completed', NOW())
            ON CONFLICT (id) DO NOTHING
        """), {"id": workout_id, "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, exercise_library_id,
             set_index, weight, load_value, load_unit, reps, rpe, set_kind,
             session_date, created_at)
        VALUES (:id, :w, :u, :en, :el, 1, :legacy, :load, :unit, :reps, :rpe,
                :kind, :d, NOW())
    """), {
        "id": str(uuid.uuid4()), "w": workout_id, "u": athlete,
        "en": exercise_name, "el": exercise_id,
        "legacy": int(load) if load is not None else None,
        "load": load, "unit": load_unit, "reps": reps, "rpe": rpe,
        "kind": set_kind, "d": day,
    })
    pg.commit()
    return workout_id


# ─────────────────────────────────────────────────────────────────────────
# The headline: the tool and the chat context agree
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_summary_tool_and_the_chat_context_report_the_same_day(pg, athlete):
    """The regression that motivated Step 18.

    A 21:00 ET meal has a `created_at` on the NEXT UTC day. The tool keyed on
    `DATE(created_at)` in UTC and the chat context on `DATE(logged_at)` in ET,
    so the same meal was counted on two different days — and whichever reader
    Sara happened to use decided what she said David had eaten.
    """
    from app.services.fitness.consumers import nutrition_day
    from app.tools.fitness.summary import FitnessSummaryTool

    today = _today(pg, athlete)
    _meal(pg, athlete, day=today, hour=21, calories=900, protein=60)

    context = nutrition_day(pg, athlete, today)
    tool = asyncio.run(FitnessSummaryTool().execute(athlete))
    assert tool.success, tool.message

    assert context["eaten"]["calories"] == 900
    assert tool.data["today_nutrition"]["totals"]["calories"] == 900
    assert tool.data["today_nutrition"]["meal_count"] == context["meal_count"] == 1


@requires_pg
def test_an_evening_meal_is_not_counted_on_tomorrow(pg, athlete):
    """`created_at` is naive UTC. For a 21:00 ET meal that is 01:00 the next
    day, so the old UTC-keyed query put dinner on tomorrow."""
    from app.services.fitness.consumers import nutrition_day

    today = _today(pg, athlete)
    _meal(pg, athlete, day=today, hour=21, calories=700)

    assert nutrition_day(pg, athlete, today)["eaten"]["calories"] == 700
    assert nutrition_day(pg, athlete, today + timedelta(days=1))["eaten"]["calories"] == 0


@requires_pg
def test_the_chat_context_renders_an_unlogged_macro_as_unknown(pg, athlete):
    """Summing NULLs to zero and subtracting told Sara the full fat budget
    was still available on a day where fat simply was not recorded. "?" and
    "0 g eaten, 90 g left" lead to different advice."""
    from app.services.fitness.consumers import nutrition_day

    today = _today(pg, athlete)
    _meal(pg, athlete, day=today, hour=12, calories=900, protein=60)

    day = nutrition_day(pg, athlete, today)
    assert day["known_fields"].get("calories") == 1
    assert day["known_fields"].get("protein") == 1
    assert not day["known_fields"].get("fat")

    rendered = asyncio.run(_render_context(pg, athlete))
    assert rendered is not None
    assert "?g fat" in rendered or "?" in rendered


async def _render_context(pg, athlete):
    from app.services.fitness_context import get_fitness_context
    return await get_fitness_context(athlete, pg)


@requires_pg
def test_the_chat_context_uses_the_resolved_target_not_the_mutable_column(
    pg, athlete,
):
    """The phase's macro columns track the CURRENT target. A dated revision is
    the only thing that can answer what the target was last month, and the
    context has to read the same resolver the Coach API does."""
    from app.schemas.fitness_coach import TargetRevisionIn, TargetScope, TargetValues
    from app.services.fitness.consumers import nutrition_day
    from app.services.fitness.targets import create_target_revision

    today = _today(pg, athlete)
    create_target_revision(pg, athlete, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=today - timedelta(days=30),
        training=TargetValues(calories=3000, protein_g=200),
    ))

    day = nutrition_day(pg, athlete, today)
    assert day["target"]["calories"] == 3000
    assert day["target"]["protein"] == 200
    assert day["target_provenance"] == "approved_revision"

    from app.services.fitness.targets import resolve_targets
    assert resolve_targets(pg, athlete, today).values.calories == 3000


# ─────────────────────────────────────────────────────────────────────────
# "workouts" means workouts
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_one_session_of_many_sets_is_one_workout(pg, athlete):
    """`workouts_count = len(set_rows)` meant one session of 24 sets told the
    weekly consolidation prompt David trained 24 times — and the report then
    reasoned about overtraining that had not happened."""
    from app.services.fitness.consumers import training_window
    from app.services.health_consolidation.data_collector import collect_activity

    day = date(2026, 9, 21)
    ex = _exercise(pg, athlete, "S18 Bench Press")
    workout_id = None
    for _ in range(8):
        workout_id = _set(pg, athlete, day=day, exercise_id=ex,
                          exercise_name="S18 Bench Press", reps=5, load=225,
                          workout_id=workout_id)

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    assert window["sets"] == 8
    assert window["sessions"] == 1

    stats = collect_activity(pg, athlete, day, day)
    assert stats.total_sets == 8
    assert stats.workouts_count == 1, (
        "the field named workouts is holding the set count again"
    )
    assert stats.workout_days == 1


@requires_pg
def test_the_workout_stats_tool_counts_the_same_sessions(pg, athlete):
    from app.services.fitness.consumers import training_window
    from app.tools.fitness.workout_log import WorkoutStatsTool

    day = date(2026, 9, 21)
    ex = _exercise(pg, athlete, "S18 Squat")
    workout_id = None
    for _ in range(5):
        workout_id = _set(pg, athlete, day=day, exercise_id=ex,
                          exercise_name="S18 Squat", reps=5, load=315,
                          workout_id=workout_id)

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    result = asyncio.run(WorkoutStatsTool().execute(
        athlete, start_date=day.isoformat(), end_date=day.isoformat(),
    ))
    assert result.success, result.message
    assert result.data["summary"]["total_workouts"] == window["sessions"] == 1
    assert result.data["summary"]["total_sets"] == window["sets"] == 5
    assert result.data["summary"]["total_volume"] == window["tonnage"]


# ─────────────────────────────────────────────────────────────────────────
# Volume means what was moved
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_volume_doubles_a_per_hand_load(pg, athlete):
    """40 lb dumbbells is 80 lb moved. `SUM(weight * reps)` counted one hand,
    so a dumbbell day looked like half the work it was."""
    from app.services.fitness.consumers import training_window

    day = date(2026, 9, 22)
    ex = _exercise(pg, athlete, "S18 DB Press", convention="per_hand")
    _set(pg, athlete, day=day, exercise_id=ex, exercise_name="S18 DB Press",
         reps=10, load=40)

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    assert window["tonnage"] == pytest.approx(800.0)
    assert window["sets_excluded_from_tonnage"] == {}


@requires_pg
def test_volume_excludes_assisted_work_rather_than_counting_the_help(pg, athlete):
    """More assistance is LESS work. Counting the assist as load ranks an
    easier set higher, which is the opposite of what a volume figure is for."""
    from app.services.fitness.consumers import training_window

    day = date(2026, 9, 22)
    ex = _exercise(pg, athlete, "S18 Assisted Pullup", convention="assisted")
    _set(pg, athlete, day=day, exercise_id=ex,
         exercise_name="S18 Assisted Pullup", reps=10, load=30)

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    assert window["tonnage"] is None
    assert sum(window["sets_excluded_from_tonnage"].values()) == 1


@requires_pg
def test_volume_keeps_a_fractional_plate(pg, athlete):
    """The legacy `weight` column is an integer, so 102.5 kg counted as 102.
    Over a session that is kilos of silently missing volume."""
    from app.services.fitness.consumers import training_window

    day = date(2026, 9, 23)
    ex = _exercise(pg, athlete, "S18 Front Squat")
    pg.execute(text("""
        INSERT INTO workout (id, user_id, title, status, created_at)
        VALUES (:id, :u, 'Session', 'completed', NOW())
    """), {"id": (wid := str(uuid.uuid4())), "u": athlete})
    pg.execute(text("""
        INSERT INTO workout_log
            (id, workout_id, user_id, exercise_id, exercise_library_id,
             set_index, weight, load_value, load_unit, reps, set_kind,
             session_date, created_at)
        VALUES (:id, :w, :u, 'S18 Front Squat', :el, 1, 102, 102.5, 'lb', 3,
                'working', :d, NOW())
    """), {"id": str(uuid.uuid4()), "w": wid, "u": athlete, "el": ex, "d": day})
    pg.commit()

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    assert window["tonnage"] == pytest.approx(307.5)
    # And the legacy integer would have given 306.
    assert window["tonnage"] != pytest.approx(306.0)


@requires_pg
def test_an_exercise_with_no_recorded_convention_is_excluded_not_assumed(
    pg, athlete,
):
    """"40" might be per hand or total. Assuming total is a guess that lands
    in a number a coach then reasons from."""
    from app.services.fitness.consumers import training_window

    day = date(2026, 9, 23)
    ex = _exercise(pg, athlete, "S18 Mystery Machine", convention=None)
    _set(pg, athlete, day=day, exercise_id=ex,
         exercise_name="S18 Mystery Machine", reps=8, load=100)

    window = training_window(pg, athlete, day, day + timedelta(days=1))
    assert window["tonnage"] is None
    assert sum(window["sets_excluded_from_tonnage"].values()) == 1


@requires_pg
def test_the_last_logged_set_in_the_brief_shows_what_was_actually_moved(
    pg, athlete,
):
    """The brief read `wl.weight`, so a 40 kg dumbbell press was spoken as 40
    while the strength analytics called the same set 80."""
    from app.services.fitness.consumers import latest_working_set

    day = date(2026, 9, 24)
    ex = _exercise(pg, athlete, "S18 Incline DB", convention="per_hand")
    _set(pg, athlete, day=day, exercise_id=ex, exercise_name="S18 Incline DB",
         reps=10, load=40)

    last = latest_working_set(pg, athlete)
    assert last is not None
    assert last["load"] == pytest.approx(40.0)
    assert last["effective_load"] == pytest.approx(80.0)
    assert last["effective_load_unavailable"] is None


@requires_pg
def test_a_voided_set_is_not_the_last_logged_set(pg, athlete):
    """A retracted set is not what David lifted. Speaking it as the last one
    is worse than saying nothing."""
    from app.services.fitness.consumers import latest_working_set

    day = date(2026, 9, 24)
    ex = _exercise(pg, athlete, "S18 Row")
    _set(pg, athlete, day=day, exercise_id=ex, exercise_name="S18 Row",
         reps=8, load=185)
    pg.execute(text("""
        UPDATE workout_log SET voided_at = NOW() WHERE user_id = :u
    """), {"u": athlete})
    pg.commit()

    assert latest_working_set(pg, athlete) is None


# ─────────────────────────────────────────────────────────────────────────
# Body weight: convert, don't drop
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_weight_logged_in_kg_is_converted_not_discarded(pg, athlete):
    """`(r.weight_unit or "lbs") == "lbs"` dropped every kg row, so a
    kg-logging week reported no weight data and the consolidation prompt was
    told David had not weighed himself."""
    from app.services.health_consolidation.data_collector import _as_lbs

    assert _as_lbs(81.0, "kg") == pytest.approx(178.57, abs=0.01)
    assert _as_lbs(178.5, "lbs") == pytest.approx(178.5)
    assert _as_lbs(178.5, None) == pytest.approx(178.5)
    # And a unit it cannot place is refused rather than guessed: 180 kg is a
    # real bodyweight, so "around 180 is probably pounds" is not available.
    assert _as_lbs(180.0, "stone") is None


@requires_pg
def test_the_weekly_weight_delta_carries_its_span(pg, athlete):
    """A change between two readings five days apart is a different claim
    from one across a full week, and the report stated both identically."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    from app.services.health_consolidation.data_collector import collect_recovery

    week_start, week_end = date(2026, 9, 21), date(2026, 9, 27)
    for offset, kg in ((0, 82.0), (5, 81.0)):
        day = week_start + timedelta(days=offset)
        ingest_observation(
            pg, athlete, metric_type="weight", value=kg, unit=Unit.KG,
            recorded_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=ET),
            source="manual", timezone_name="America/New_York",
        )
    pg.commit()

    stats = collect_recovery(pg, athlete, week_start, week_end)
    assert stats.weight_days_observed == 2
    assert stats.weight_days_expected == 7
    assert stats.weight_delta_span_days == 5
    assert stats.weight_delta_lbs == pytest.approx(-2.2, abs=0.05)


@requires_pg
def test_one_weigh_in_is_a_weight_not_a_trend(pg, athlete):
    """Reporting delta 0 from a single reading says "no change", which is a
    claim a single reading cannot support."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    from app.services.health_consolidation.data_collector import collect_recovery

    week_start, week_end = date(2026, 9, 21), date(2026, 9, 27)
    ingest_observation(
        pg, athlete, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=datetime(2026, 9, 23, 7, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()

    stats = collect_recovery(pg, athlete, week_start, week_end)
    assert stats.weight_days_observed == 1
    assert stats.weight_delta_lbs is None
    assert stats.weight_delta_span_days is None
    assert stats.weight_lbs_end is not None


@requires_pg
def test_no_weigh_ins_at_all_claims_nothing(pg, athlete):
    from app.services.health_consolidation.data_collector import collect_recovery

    stats = collect_recovery(pg, athlete, date(2026, 9, 21), date(2026, 9, 27))
    assert stats.weight_delta_lbs is None
    assert stats.weight_lbs_start is None
    assert stats.weight_lbs_end is None


# ─────────────────────────────────────────────────────────────────────────
# Averages over confirmed days
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_weekly_macro_average_uses_only_confirmed_days(pg, athlete):
    """Averaging every day with any row counts a logged breakfast as a day's
    eating, which is how a maintenance week reads as a crash diet."""
    from app.services.health_consolidation.data_collector import collect_activity

    week_start, week_end = date(2026, 9, 21), date(2026, 9, 27)
    for offset in (0, 1, 2):
        _meal(pg, athlete, day=week_start + timedelta(days=offset), hour=12,
              calories=3000, protein=200)
    # A day with one logged breakfast and nothing else.
    _meal(pg, athlete, day=week_start + timedelta(days=3), hour=8, calories=400)

    for offset in (0, 1, 2):
        _confirm(pg, athlete, week_start + timedelta(days=offset))

    stats = collect_activity(pg, athlete, week_start, week_end)
    assert stats.food_days == 4
    assert stats.food_complete_days == 3
    assert stats.food_partial_days == 1
    assert stats.avg_calories == pytest.approx(3000.0)
    assert stats.macro_average_unavailable is None


@requires_pg
def test_with_no_confirmed_day_the_average_is_withheld_with_a_reason(
    pg, athlete,
):
    """An average over partial days estimates what David remembered to log,
    not what he ate — and the report would read it as the latter."""
    from app.services.health_consolidation.data_collector import collect_activity

    week_start, week_end = date(2026, 9, 21), date(2026, 9, 27)
    _meal(pg, athlete, day=week_start, hour=8, calories=400)

    stats = collect_activity(pg, athlete, week_start, week_end)
    assert stats.avg_calories is None
    assert stats.food_complete_days == 0
    assert "logging habits" in (stats.macro_average_unavailable or "")
    # The per-day rows are still there, so the report can show what WAS logged.
    assert stats.food_by_date[week_start.isoformat()]["calories"] == 400.0


def _confirm(pg, athlete, day: date):
    pg.execute(text("""
        INSERT INTO daily_recovery_log
            (id, user_id, log_date, nutrition_status, nutrition_completed_at,
             created_at, updated_at)
        VALUES (:i, :u, :d, 'complete', NOW(), NOW(), NOW())
        ON CONFLICT (user_id, log_date) DO UPDATE
        SET nutrition_status = 'complete', nutrition_completed_at = NOW()
    """), {"i": str(uuid.uuid4()), "u": athlete, "d": day})
    pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Payload size
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_chat_context_stays_compact_with_a_busy_day(pg, athlete):
    """§18.5: render compact state, not raw months of meals. A context
    fragment that grows with the log pushes something else out of the prompt,
    and which thing is unknowable from here."""
    today = _today(pg, athlete)
    for hour in range(6, 22):
        _meal(pg, athlete, day=today, hour=hour, calories=200, protein=15,
              name=f"item {hour}")

    rendered = asyncio.run(_render_context(pg, athlete))
    assert rendered is not None
    assert len(rendered) < 2500, (
        f"the nutrition fragment grew to {len(rendered)} chars"
    )


@requires_pg
def test_the_summary_tool_does_not_return_every_set_of_the_window(pg, athlete):
    from app.tools.fitness.summary import FitnessSummaryTool

    today = _today(pg, athlete)
    ex = _exercise(pg, athlete, "S18 Volume Test")
    for offset in range(3):
        workout_id = None
        for _ in range(10):
            workout_id = _set(pg, athlete, day=today - timedelta(days=offset),
                              exercise_id=ex, exercise_name="S18 Volume Test",
                              reps=8, load=135, workout_id=workout_id)

    result = asyncio.run(FitnessSummaryTool().execute(athlete, days_back=7))
    assert result.success, result.message
    assert len(result.data["recent_workouts"]["workouts"]) <= 10
    assert result.data["this_week"]["total_sets"] >= 10


# ─────────────────────────────────────────────────────────────────────────
# Owner scope survives the delegation
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_shared_readers_refuse_a_missing_owner(pg):
    """Every one of these used to be called with a `user_id` that could be a
    solo-owner stub. There is no default owner here."""
    from app.services.fitness.consumers import (
        food_days_payload, latest_working_set, nutrition_day, training_window,
        weight_window,
    )
    from app.services.fitness.data_access import FitnessDataError

    start, end = date(2026, 9, 21), date(2026, 9, 28)
    for call in (
        lambda: nutrition_day(pg, ""),
        lambda: training_window(pg, "", start, end),
        lambda: food_days_payload(pg, "", start, end),
        lambda: weight_window(pg, "", start, end),
        lambda: latest_working_set(pg, ""),
    ):
        with pytest.raises((FitnessDataError, ValueError)):
            call()


# ─────────────────────────────────────────────────────────────────────────
# The dashboard endpoint reads the same resolvers
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_dashboard_target_endpoint_matches_the_coach_resolver(pg, athlete):
    """`/api/fitness/today-target` is what the web dashboard, the food log and
    the iOS app read. It used to pick macros straight off the phase's mutable
    columns and re-implement training-day detection inline, so it could
    disagree with the chat context about both answers at once.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision, resolve_targets

    today = _today(pg, athlete)
    create_target_revision(pg, athlete, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=today - timedelta(days=10),
        training=TargetValues(calories=3200, protein_g=210),
        rest=TargetValues(calories=2800, protein_g=210),
    ))

    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    response = client.get(
        "/api/fitness/today-target",
        headers={"Authorization": f"Bearer {create_access_token({'sub': athlete})}"},
    )
    assert response.status_code == 200, response.text
    served = response.json()

    resolved = resolve_targets(pg, athlete, today)
    assert served["target"]["calories"] == resolved.values.calories
    assert served["target"]["protein"] == resolved.values.protein_g
    assert served["day_type"] == resolved.day_type.value
    assert served["target_provenance"] == "approved_revision"
    # The boolean the old readers use still agrees with the richer field.
    assert served["is_training_day"] == (served["day_type"] == "training")


@requires_pg
def test_the_dashboard_endpoint_returns_targets_with_no_phase(pg, athlete):
    """A user-scoped revision is a real target even with no program attached.

    The old handler returned `target: null` whenever there was no active
    phase, because the phase row was where it read the macros from — so an
    athlete with targets and no block saw none.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision

    today = _today(pg, athlete)
    create_target_revision(pg, athlete, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=today - timedelta(days=3),
        training=TargetValues(calories=2900, protein_g=190),
    ))

    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    served = client.get(
        "/api/fitness/today-target",
        headers={"Authorization": f"Bearer {create_access_token({'sub': athlete})}"},
    ).json()

    assert served["phase"] is None
    assert served["target"]["calories"] == 2900
