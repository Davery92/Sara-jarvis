"""Step 9 of FITNESS_COACH_IMPLEMENTATION_PLAN: a day can be partially logged
without fabricating the rest of it, and nutrition completeness is explicit.

Two defects this pins down, both of which produce confident wrong output
rather than an error:

* `recovery_score.compute_readiness({})` returns **100, "Excellent — good to
  push it today"**. That is correct arithmetic on no information, and it has
  been shown to someone who logged nothing. The formula is untouched here;
  what changes is that an empty day reports no score and `coverage=unknown`.
* A PATCH that cannot distinguish "I did not mention HRV" from "clear my
  HRV" either wipes the wearable's reading or makes clearing impossible.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_checkins_pg.py
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
DAY = date(2026, 10, 1)


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
    alice = f"m4a-{uuid.uuid4().hex[:18]}"
    bob = f"m4b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m4.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for t in ("health_metric", "weight_trend", "daily_recovery_log",
              "food_log", "fitness_athlete_profile"):
        pg.execute(text(f"DELETE FROM {t} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _patch(pg, user_id, day=DAY, **kwargs):
    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.observations import patch_check_in
    return patch_check_in(pg, user_id, day, CheckInPatch(**kwargs))


# ─────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_there_is_still_exactly_one_daily_row_per_athlete_per_day(pg, two_athletes):
    """Extended, not duplicated.

    A second daily-truth table is how two screens come to show different
    answers for the same day.
    """
    alice, _ = two_athletes
    _patch(pg, alice, energy=7)
    _patch(pg, alice, fatigue=4)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM daily_recovery_log WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).scalar() == 1

    tables = {r[0] for r in pg.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE '%check%in%'
    """)).fetchall()}
    assert tables == set(), f"a separate check-in table appeared: {tables}"


@requires_pg
def test_subjective_fields_default_to_null_not_to_a_midpoint(pg, two_athletes):
    """Nobody recorded their stress last March.

    A default of 5 would be a fabricated data point indistinguishable from a
    real one.
    """
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO daily_recovery_log (id, user_id, log_date, created_at, updated_at)
        VALUES (:id, :u, :d, NOW(), NOW())
    """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY})
    pg.commit()
    row = pg.execute(text("""
        SELECT sleep_quality, energy, fatigue, stress, motivation,
               subjective_readiness, nutrition_status, nutrition_completed_at,
               row_version, field_sources
        FROM daily_recovery_log WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).fetchone()
    for field in ("sleep_quality", "energy", "fatigue", "stress", "motivation",
                  "subjective_readiness"):
        assert getattr(row, field) is None, f"{field} was given a default"
    assert row.nutrition_status == "unknown", (
        "a day with no meals logged is unknown, not partial — partial would "
        "put it in the nutrition denominator"
    )
    assert row.nutrition_completed_at is None
    assert row.row_version == 1
    assert row.field_sources == {}


@requires_pg
@pytest.mark.parametrize("field", [
    "sleep_quality", "energy", "fatigue", "stress", "motivation",
    "subjective_readiness",
])
@pytest.mark.parametrize("bad", [0, 11, -3])
def test_scale_constraints_reject_out_of_range(pg, two_athletes, field, bad):
    """A 0 or an 11 from a client would silently skew every mean."""
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text(f"""
            INSERT INTO daily_recovery_log (id, user_id, log_date, {field}, created_at, updated_at)
            VALUES (:id, :u, :d, :v, NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY, "v": bad})
        pg.commit()
    pg.rollback()


@requires_pg
def test_nutrition_status_is_constrained_and_complete_needs_a_timestamp(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, nutrition_status, created_at, updated_at)
            VALUES (:id, :u, :d, 'mostly', NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY})
        pg.commit()
    pg.rollback()

    # "complete" without a confirmation time is incoherent: editing a meal
    # afterwards has to be able to invalidate the confirmation, and that
    # decision needs to know when it was made.
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, nutrition_status, created_at, updated_at)
            VALUES (:id, :u, :d, 'complete', NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY})
        pg.commit()
    pg.rollback()


@requires_pg
def test_an_impossible_sleep_episode_is_rejected(pg, two_athletes):
    alice, _ = two_athletes
    for bed, wake in (
        (datetime(2026, 10, 1, 23, 0, tzinfo=UTC), datetime(2026, 10, 1, 22, 0, tzinfo=UTC)),
        (datetime(2026, 10, 1, 23, 0, tzinfo=UTC), datetime(2026, 10, 3, 23, 30, tzinfo=UTC)),
    ):
        with pytest.raises(IntegrityError):
            pg.execute(text("""
                INSERT INTO daily_recovery_log
                    (id, user_id, log_date, bedtime_at, wake_at, created_at, updated_at)
                VALUES (:id, :u, :d, :b, :w, NOW(), NOW())
            """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY, "b": bed, "w": wake})
            pg.commit()
        pg.rollback()


@requires_pg
def test_the_existing_soreness_constraint_still_holds(pg, two_athletes):
    """M4 must not have weakened what was already enforced."""
    alice, _ = two_athletes
    with pytest.raises(IntegrityError):
        pg.execute(text("""
            INSERT INTO daily_recovery_log
                (id, user_id, log_date, soreness_level, created_at, updated_at)
            VALUES (:id, :u, :d, 15, NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "d": DAY})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Partial updates
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_partial_patch_preserves_everything_it_did_not_mention(pg, two_athletes):
    """The core requirement.

    HealthKit writes HRV and sleep in the morning. The athlete answers
    "energy: 7" at lunchtime. That must not erase the morning's readings.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation

    alice, _ = two_athletes
    ingest_observation(pg, alice, metric_type="hrv", value=68.0, unit=Unit.MS,
                       recorded_at=datetime(2026, 10, 1, 6, 30, tzinfo=ET),
                       source="apple_health", external_id="hk-hrv")
    ingest_observation(pg, alice, metric_type="sleep_hours", value=7.4,
                       unit=Unit.HOUR,
                       recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
                       source="apple_health", external_id="hk-sleep")
    pg.commit()

    first = _patch(pg, alice, soreness_level=4)
    assert first.soreness_level == 4
    assert first.hrv.value == 68.0
    assert first.sleep_duration.value == 7.4

    second = _patch(pg, alice, energy=7)
    assert second.energy == 7
    assert second.soreness_level == 4, "an earlier answer was erased"
    assert second.hrv.value == 68.0, "the wearable's reading was erased"
    assert second.sleep_duration.value == 7.4


@requires_pg
def test_an_explicit_null_clears_only_the_chosen_field(pg, two_athletes):
    alice, _ = two_athletes
    _patch(pg, alice, energy=7, fatigue=5, soreness_level=3)

    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.observations import patch_check_in
    out = patch_check_in(pg, alice, DAY, CheckInPatch(fatigue=None))

    assert out.fatigue is None, "an explicit null must clear"
    assert out.energy == 7, "a field not mentioned must survive"
    assert out.soreness_level == 3


@requires_pg
def test_a_physiological_field_is_rerouted_to_the_canonical_store(pg, two_athletes):
    """A weight typed into the check-in is an observation.

    Writing it only onto the daily row would create a second answer to "what
    did I weigh on 1 October".
    """
    alice, _ = two_athletes
    out = _patch(pg, alice, **{})  # create the row first
    out = _patch(pg, alice, energy=6)

    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.observations import patch_check_in
    out = patch_check_in(pg, alice, DAY, CheckInPatch(**{"energy": 6}))

    # Now a delegated field, through the same PATCH shape the API uses.
    from app.services.fitness.observations import _ingest_delegated
    _ingest_delegated(pg, alice, "body_weight", 181.4, DAY, "America/New_York", "manual")
    pg.commit()

    observation = pg.execute(text("""
        SELECT value, unit, source_quality FROM health_metric
        WHERE user_id = :u AND metric_type = 'weight'
    """), {"u": alice}).fetchone()
    assert observation is not None
    assert float(observation.value) == pytest.approx(181.4)
    assert observation.unit == "lb"
    assert observation.source_quality == "manual"

    from app.services.fitness.observations import get_check_in
    reread = get_check_in(pg, alice, DAY)
    assert reread.weight.value == pytest.approx(181.4)


@requires_pg
def test_clearing_a_physiological_field_through_a_patch_is_refused(pg, two_athletes):
    """Deleting an observation is a correction, not a field clear.

    It needs a target and a reason, so silently dropping it would lose both.
    """
    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.observations import patch_check_in

    alice, _ = two_athletes
    # `hrv` is accepted as a value but refused as a clear.
    with pytest.raises(FitnessDataError) as e:
        patch_check_in(pg, alice, DAY, CheckInPatch(**{"hrv": None}))
    assert "correct the observation" in str(e.value)
    pg.rollback()


@requires_pg
def test_field_sources_record_where_each_answer_came_from(pg, two_athletes):
    alice, _ = two_athletes
    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.observations import patch_check_in

    patch_check_in(pg, alice, DAY, CheckInPatch(energy=7), source="manual")
    patch_check_in(pg, alice, DAY, CheckInPatch(fatigue=4), source="chat")
    out = patch_check_in(pg, alice, DAY, CheckInPatch(energy=5), source="correction")

    assert out.field_sources["fatigue"] == "chat"
    assert out.field_sources["energy"] == "correction", (
        "a correction must be distinguishable from the original answer"
    )


@requires_pg
def test_concurrent_edits_conflict_rather_than_overwrite(pg, two_athletes):
    alice, _ = two_athletes
    from app.schemas.fitness_coach import CheckInPatch
    from app.services.fitness.observations import CheckInConflict, patch_check_in

    first = _patch(pg, alice, energy=7)
    version = first.row_version

    _patch(pg, alice, fatigue=4)  # something else moved it on

    with pytest.raises(CheckInConflict) as e:
        patch_check_in(pg, alice, DAY,
                       CheckInPatch(energy=3, expected_version=version))
    assert isinstance(e.value.current_version, int)
    pg.rollback()

    # The earlier value survived the refused write.
    from app.services.fitness.observations import get_check_in
    assert get_check_in(pg, alice, DAY).energy == 7


@requires_pg
def test_row_version_increments_on_every_applied_edit(pg, two_athletes):
    alice, _ = two_athletes
    v1 = _patch(pg, alice, energy=7).row_version
    v2 = _patch(pg, alice, fatigue=4).row_version
    assert v2 > v1


@requires_pg
def test_an_unknown_field_is_refused(pg, two_athletes):
    alice, _ = two_athletes
    from app.schemas.fitness_coach import CheckInPatch
    with pytest.raises(Exception):
        CheckInPatch(vibes=9)


# ─────────────────────────────────────────────────────────────────────────
# Readiness coverage
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_empty_day_has_no_readiness_score_at_all(pg, two_athletes):
    """`compute_readiness({})` returns 100/"Excellent".

    That has been displayed to someone who logged nothing. The formula is not
    changed — rewriting it would change every historical score — but an input
    with nothing eligible now produces no score.
    """
    from app.schemas.fitness_coach import ReadinessCoverage
    from app.services.fitness.observations import get_check_in
    from app.services.recovery_score import compute_readiness

    # The formula's behaviour on empty input, unchanged:
    assert compute_readiness({})["score"] == 100
    assert compute_readiness({})["label"] == "Excellent"

    alice, _ = two_athletes
    out = get_check_in(pg, alice, DAY)
    assert out.computed_readiness is None, (
        "an empty day must not report a score of any kind"
    )
    assert out.readiness_coverage is ReadinessCoverage.UNKNOWN


@requires_pg
def test_partial_inputs_are_labelled_partial_with_what_is_missing(pg, two_athletes):
    from app.schemas.fitness_coach import ReadinessCoverage, Unit
    from app.services.fitness.observations import get_check_in, ingest_observation

    alice, _ = two_athletes
    ingest_observation(pg, alice, metric_type="sleep_hours", value=7.5,
                       unit=Unit.HOUR,
                       recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
                       source="apple_health", external_id="s1")
    pg.commit()
    _patch(pg, alice, soreness_level=3)

    out = get_check_in(pg, alice, DAY)
    assert out.computed_readiness is not None
    assert out.readiness_coverage is ReadinessCoverage.PARTIAL
    assert out.computed_readiness["coverage"] == "partial"
    assert sorted(out.computed_readiness["inputs_used"]) == ["sleep_hours", "soreness_level"]
    assert "hrv" in out.computed_readiness["inputs_missing"]
    assert "heart_rate" in out.computed_readiness["inputs_missing"]


@requires_pg
def test_a_full_day_is_labelled_full_and_uses_the_established_formula(pg, two_athletes):
    from app.schemas.fitness_coach import ReadinessCoverage, Unit
    from app.services.fitness.observations import get_check_in, ingest_observation
    from app.services.recovery_score import compute_readiness

    alice, _ = two_athletes
    for metric_type, value, unit, hour in (
        ("sleep_hours", 5.5, Unit.HOUR, 7),
        ("hrv", 45.0, Unit.MS, 6),
        ("resting_heart_rate", 62.0, Unit.BPM, 6),
    ):
        ingest_observation(pg, alice, metric_type=metric_type, value=value, unit=unit,
                           recorded_at=datetime(2026, 10, 1, hour, 30, tzinfo=ET),
                           source="apple_health", external_id=f"{metric_type}-1")
    pg.commit()
    _patch(pg, alice, soreness_level=8)

    out = get_check_in(pg, alice, DAY)
    assert out.readiness_coverage is ReadinessCoverage.FULL
    assert out.computed_readiness["inputs_missing"] == []

    # The score is exactly what the established formula produces for these
    # inputs — this work wraps it, it does not replace it.
    expected = compute_readiness(
        {"sleep_hours": 5.5, "hrv": 45.0, "heart_rate": 62.0, "soreness_level": 8},
        {},
    )
    assert out.computed_readiness["score"] == expected["score"]
    assert out.computed_readiness["label"] == expected["label"]


@requires_pg
def test_subjective_readiness_is_not_the_computed_score(pg, two_athletes):
    """Two different facts.

    "I feel like a 4" and "the formula says 82" are both true and neither
    substitutes for the other.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import get_check_in, ingest_observation

    alice, _ = two_athletes
    ingest_observation(pg, alice, metric_type="sleep_hours", value=8.0,
                       unit=Unit.HOUR,
                       recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET),
                       source="apple_health", external_id="s2")
    pg.commit()
    _patch(pg, alice, subjective_readiness=4)

    out = get_check_in(pg, alice, DAY)
    assert out.subjective_readiness == 4
    assert out.computed_readiness is not None
    assert out.computed_readiness["score"] != 4


# ─────────────────────────────────────────────────────────────────────────
# Nutrition completeness
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_marking_nutrition_complete_is_explicit_and_timestamped(pg, two_athletes):
    from app.schemas.fitness_coach import NutritionStatus
    alice, _ = two_athletes
    out = _patch(pg, alice, nutrition_status="complete")
    assert out.nutrition_status is NutritionStatus.COMPLETE
    assert out.nutrition_completed_at is not None


@requires_pg
def test_completion_is_never_inferred_from_logged_meals(pg, two_athletes):
    """Three meals and 2,800 calories is not a confirmation.

    Inferring it would inflate the complete-day count, which is the
    denominator for every nutrition average.
    """
    from app.schemas.fitness_coach import NutritionStatus
    from app.services.fitness.observations import get_check_in

    alice, _ = two_athletes
    for meal, calories in (("breakfast", 700), ("lunch", 900), ("dinner", 1200)):
        pg.execute(text("""
            INSERT INTO food_log
                (id, user_id, meal_type, food_items, calories, protein, carbs, fats,
                 logged_at, created_at, updated_at)
            VALUES (:id, :u, :m, '[]', :c, 50, 80, 25,
                    :logged, NOW(), NOW())
        """), {"id": str(uuid.uuid4()), "u": alice, "m": meal, "c": calories,
               "logged": datetime(2026, 10, 1, 12, 0)})
    pg.commit()

    out = get_check_in(pg, alice, DAY)
    assert out.nutrition_status is NutritionStatus.UNKNOWN, (
        "logging meals is not the same as confirming the day is complete"
    )


@requires_pg
def test_editing_a_meal_revokes_the_days_confirmation(pg, two_athletes):
    """Default policy: invalidate until reconfirmed.

    Keeping the mark would leave the day counted as complete with totals that
    no longer match what was confirmed.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    meal_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, protein, carbs, fats,
             logged_at, created_at, updated_at)
        VALUES (:id, :u, 'lunch', '[]', 900, 60, 90, 30, :logged, NOW(), NOW())
    """), {"id": meal_id, "u": alice, "logged": datetime(2026, 10, 1, 12, 30)})
    pg.commit()

    _patch(pg, alice, nutrition_status="complete")
    assert pg.execute(text("""
        SELECT nutrition_status FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).scalar() == "complete"

    r = client.put(f"/api/fitness/food-log/{meal_id}", headers=headers, json={
        "meal_type": "lunch",
        "food_items": [{"name": "chicken", "quantity": 2, "unit": "serving"}],
    })
    assert r.status_code == 200, r.text

    row = pg.execute(text("""
        SELECT nutrition_status, nutrition_completed_at, field_sources
        FROM daily_recovery_log WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).fetchone()
    assert row.nutrition_status == "partial"
    assert row.nutrition_completed_at is None
    assert "invalidated" in str(row.field_sources.get("nutrition_status", ""))


@requires_pg
def test_deleting_a_meal_revokes_the_days_confirmation(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    meal_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, logged_at, created_at, updated_at)
        VALUES (:id, :u, 'dinner', '[]', 1100, :logged, NOW(), NOW())
    """), {"id": meal_id, "u": alice, "logged": datetime(2026, 10, 1, 19, 0)})
    pg.commit()
    _patch(pg, alice, nutrition_status="complete")

    assert client.delete(f"/api/fitness/food-log/{meal_id}",
                         headers=headers).status_code == 200

    assert pg.execute(text("""
        SELECT nutrition_status FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).scalar() == "partial"


@requires_pg
def test_relabelling_a_meal_does_not_revoke_the_confirmation(pg, two_athletes):
    """`PATCH` changes `meal_type`/`notes` only.

    Neither changes what was eaten, so the day's totals are still exactly
    what the athlete confirmed. Revoking for a relabel would drop a
    genuinely complete day out of the denominator.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    meal_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, logged_at, created_at, updated_at)
        VALUES (:id, :u, 'lunch', '[]', 900, :logged, NOW(), NOW())
    """), {"id": meal_id, "u": alice, "logged": datetime(2026, 10, 1, 12, 30)})
    pg.commit()
    _patch(pg, alice, nutrition_status="complete")

    r = client.patch(f"/api/fitness/food-log/{meal_id}", headers=headers,
                     json={"meal_type": "dinner"})
    assert r.status_code == 200, r.text
    assert pg.execute(text("""
        SELECT nutrition_status FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).scalar() == "complete"


@requires_pg
def test_reconfirming_after_an_edit_works(pg, two_athletes):
    from app.schemas.fitness_coach import NutritionStatus
    from app.services.fitness.observations import invalidate_nutrition_completion

    alice, _ = two_athletes
    _patch(pg, alice, nutrition_status="complete")
    assert invalidate_nutrition_completion(pg, alice, DAY, reason="meal_edited") is True
    pg.commit()

    again = _patch(pg, alice, nutrition_status="complete")
    assert again.nutrition_status is NutritionStatus.COMPLETE
    assert again.nutrition_completed_at is not None


@requires_pg
def test_invalidation_is_a_no_op_on_a_day_that_was_never_confirmed(pg, two_athletes):
    from app.services.fitness.observations import invalidate_nutrition_completion
    alice, _ = two_athletes
    _patch(pg, alice, energy=6)
    assert invalidate_nutrition_completion(pg, alice, DAY, reason="meal_edited") is False


# ─────────────────────────────────────────────────────────────────────────
# Existing consumers
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_legacy_recovery_endpoint_still_works_unchanged(pg, two_athletes):
    """The iOS app and the Recovery card read this shape."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.post("/api/fitness/recovery", headers=headers, json={
        "log_date": "2026-10-01", "hrv": 70, "heart_rate": 54,
        "sleep_hours": 7.5, "soreness_level": 2, "notes": "felt good",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    for field in ("hrv", "heart_rate", "sleep_hours", "soreness_level", "notes"):
        assert field in body
    assert body["hrv"] == 70

    g = client.get("/api/fitness/recovery/2026-10-01", headers=headers)
    assert g.status_code == 200
    assert g.json()["soreness_level"] == 2


@requires_pg
def test_the_coach_check_in_api_round_trip(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, bob = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    a = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}
    b = {"Authorization": f"Bearer {create_access_token({'sub': bob})}"}

    assert client.get("/api/fitness/coach/check-ins/2026-10-01").status_code == 401

    empty = client.get("/api/fitness/coach/check-ins/2026-10-01", headers=a)
    assert empty.status_code == 200
    body = empty.json()
    assert body["nutrition_status"] == "unknown"
    assert body["computed_readiness"] is None
    assert body["readiness_coverage"] == "unknown"
    assert body["weight"]["value"] is None
    assert body["weight"]["unavailable_reason"] == "no_data"

    r = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=a,
                     json={"energy": 7, "soreness_level": 4})
    assert r.status_code == 200, r.text
    version = r.json()["row_version"]

    # Omitted survives, explicit null clears.
    r = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=a,
                     json={"motivation": 8})
    assert r.json()["energy"] == 7
    r = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=a,
                     json={"energy": None})
    assert r.json()["energy"] is None
    assert r.json()["motivation"] == 8

    # Out-of-range is a 422 from the DTO, before any SQL.
    assert client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=a,
                        json={"energy": 42}).status_code == 422

    # A stale version is a 409 carrying the current one.
    conflict = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=a,
                            json={"energy": 1, "expected_version": version})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "version_conflict"
    assert isinstance(conflict.json()["detail"]["current_version"], int)

    # Bob's day is his own.
    assert client.get("/api/fitness/coach/check-ins/2026-10-01",
                      headers=b).json()["motivation"] is None


@requires_pg
def test_check_ins_do_not_cross_between_athletes(pg, two_athletes):
    from app.services.fitness.observations import get_check_in
    alice, bob = two_athletes
    _patch(pg, alice, energy=9)
    _patch(pg, bob, energy=2)
    assert get_check_in(pg, alice, DAY).energy == 9
    assert get_check_in(pg, bob, DAY).energy == 2


@requires_pg
def test_a_check_in_belongs_to_the_athletes_calendar_day(pg, two_athletes):
    from app.schemas.fitness_coach import AthleteProfilePatch, Unit
    from app.services.fitness.observations import get_check_in, ingest_observation
    from app.services.fitness.profile import patch_athlete_profile

    alice, _ = two_athletes
    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="Asia/Tokyo"))

    # 08:00 Tokyo on 2 October is 19:00 ET on the 1st.
    ingest_observation(
        pg, alice, metric_type="weight", value=80.0, unit=Unit.KG,
        recorded_at=datetime(2026, 10, 2, 8, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        source="manual",
    )
    pg.commit()

    assert get_check_in(pg, alice, date(2026, 10, 2)).weight.value is not None, (
        "the observation belongs to the athlete's 2 October, not ET's 1st"
    )
    assert get_check_in(pg, alice, date(2026, 10, 1)).weight.value is None


@requires_pg
def test_the_api_accepts_a_weight_and_stores_it_as_an_observation(pg, two_athletes):
    """`body_weight` on a check-in PATCH is not a check-in column.

    It is accepted because that is how a Today screen supplies it, and then
    rerouted to `health_metric` — so the day's weight has one answer rather
    than one on the daily row and one in the canonical store.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=headers,
                     json={"body_weight": 181.6, "sleep_hours": 7.25, "energy": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["energy"] == 7
    assert body["weight"]["value"] == pytest.approx(181.6)
    assert body["weight"]["unit"] == "lb"
    assert body["sleep_duration"]["value"] == pytest.approx(7.25)

    stored = {
        row.metric_type: float(row.value) for row in pg.execute(text("""
            SELECT metric_type, value FROM health_metric WHERE user_id = :u
        """), {"u": alice}).fetchall()
    }
    assert stored["weight"] == pytest.approx(181.6)
    assert stored["sleep_hours"] == pytest.approx(7.25)

    # The daily row's legacy mirrors follow from the canonical value.
    mirror = pg.execute(text("""
        SELECT body_weight, sleep_hours FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": DAY}).fetchone()
    assert float(mirror.body_weight) == pytest.approx(181.6)
    assert float(mirror.sleep_hours) == pytest.approx(7.25)


@requires_pg
def test_the_api_refuses_an_impossible_physiological_value(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    for payload in ({"body_weight": 0}, {"body_weight": -5},
                    {"sleep_hours": 30}, {"hrv": 0}):
        r = client.patch("/api/fitness/coach/check-ins/2026-10-01",
                         headers=headers, json=payload)
        assert r.status_code == 422, f"{payload} was accepted"
    assert pg.execute(text(
        "SELECT COUNT(*) FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar() == 0


@requires_pg
def test_clearing_a_weight_through_the_api_is_a_409_shaped_refusal(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness_coach import router

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.patch("/api/fitness/coach/check-ins/2026-10-01", headers=headers,
                     json={"body_weight": None})
    assert r.status_code == 422
    assert "correct the observation" in r.text
