"""Step 8 of FITNESS_COACH_IMPLEMENTATION_PLAN: every path that writes a body
number goes through one ingest, and the selection rules do not quietly
inflate a day's figure.

The failure modes being prevented, each of which produces a plausible wrong
number rather than an error:

* Summing HealthKit's cumulative step samples (they are running totals, so
  summing counts the same steps repeatedly).
* Summing two devices' overlapping sleep totals (two sources each saying
  "7.5h last night" is one night of 7.5 hours, not fifteen).
* Averaging all of a day's weigh-ins (three weigh-ins one day and one the
  next gives the first day three times the influence on a weekly mean, which
  then reads as a trend).
* Guessing a unit from a magnitude (180 lb and 180 kg are both real
  bodyweights).
* `ON CONFLICT DO NOTHING` discarding a second source's disagreeing value
  with no trace.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_observation_ingest_pg.py
"""
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
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"m3a-{uuid.uuid4().hex[:18]}"
    bob = f"m3b-{uuid.uuid4().hex[:18]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@m3.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for t in ("health_metric", "weight_trend", "daily_recovery_log",
              "fitness_athlete_profile"):
        pg.execute(text(f"DELETE FROM {t} WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"), {"ids": [alice, bob]})
    pg.commit()


def _ingest(pg, user_id, **kwargs):
    from app.services.fitness.observations import ingest_observation
    return ingest_observation(pg, user_id, **kwargs)


# ─────────────────────────────────────────────────────────────────────────
# Units
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_value_is_converted_to_canonical_and_the_original_is_kept(pg, two_athletes):
    """A kg→lb conversion must be reversible.

    Without `original_value`/`original_unit`, a later change to the
    canonical-unit policy cannot be re-derived and the athlete's actual
    entry is gone.
    """
    from app.schemas.fitness_coach import Unit
    alice, _ = two_athletes

    result = _ingest(
        pg, alice, metric_type="weight", value=81.5, unit=Unit.KG,
        recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), source="manual",
    )
    pg.commit()
    assert result.stored

    row = pg.execute(text("""
        SELECT value, unit, original_value, original_unit, metadata
        FROM health_metric WHERE id = :id
    """), {"id": result.observation_id}).fetchone()

    assert row.unit == "lb"
    assert float(row.value) == pytest.approx(179.6766, abs=1e-3)
    assert float(row.original_value) == 81.5
    assert row.original_unit == "kg"
    assert row.metadata["converted_from"]["unit"] == "kg"


@requires_pg
def test_no_unit_is_ever_inferred_from_a_magnitude(pg, two_athletes):
    """A type with no traced canonical unit must be refused, not guessed."""
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes

    with pytest.raises(FitnessDataError) as e:
        _ingest(pg, alice, metric_type="grip_strength", value=52.0, unit=None,
                recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), source="manual")
    assert "magnitude does not disclose" in str(e.value)
    pg.rollback()


@requires_pg
def test_an_implicit_unit_is_accepted_for_a_traced_type_and_recorded(pg, two_athletes):
    """The compatibility path: existing writers send no unit.

    Those writers have always meant the canonical unit. That is now written
    down on the row instead of being a convention readers have to know.
    """
    alice, _ = two_athletes
    result = _ingest(pg, alice, metric_type="weight", value=182.0, unit=None,
                     recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                     source="apple_health")
    pg.commit()
    row = pg.execute(text("SELECT unit, original_value FROM health_metric WHERE id = :id"),
                     {"id": result.observation_id}).fetchone()
    assert row.unit == "lb"
    assert row.original_value is None, "no conversion happened, so nothing to preserve"


@requires_pg
def test_nan_and_infinity_are_refused_before_storage(pg, two_athletes):
    from app.schemas.fitness_coach import Unit, UnitError
    alice, _ = two_athletes
    for bad in (float("nan"), float("inf")):
        with pytest.raises((UnitError, ValueError)):
            _ingest(pg, alice, metric_type="weight", value=bad, unit=Unit.LB,
                    recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                    source="manual")
    pg.rollback()
    assert pg.execute(text(
        "SELECT COUNT(*) FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar() == 0


@requires_pg
def test_a_naive_recorded_at_is_refused(pg, two_athletes):
    """A naive timestamp cannot be placed on an athlete-local calendar day."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    with pytest.raises(FitnessDataError) as e:
        _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
                recorded_at=datetime(2026, 10, 1, 12, 0), source="manual")
    assert "timezone-aware" in str(e.value)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Idempotency and conflict
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_replayed_provider_sample_is_a_no_op(pg, two_athletes):
    """A retried sync batch must not double-store.

    Matching on the provider's own sample id rather than on the timestamp,
    because a timestamp has to match to the microsecond and a re-serialized
    one often does not.
    """
    from app.schemas.fitness_coach import Unit
    alice, _ = two_athletes
    kwargs = dict(
        metric_type="weight", value=180.4, unit=Unit.LB, source="apple_health",
        external_id="HKQuantitySample-ABC-123",
    )
    first = _ingest(pg, alice, recorded_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC), **kwargs)
    pg.commit()
    # The retry arrives with a slightly different serialized timestamp, which
    # is exactly why the sample id is the key.
    second = _ingest(pg, alice, recorded_at=datetime(2026, 10, 1, 11, 0, 0, 500, tzinfo=UTC),
                     **kwargs)
    pg.commit()

    assert first.stored and not second.stored
    assert second.duplicate
    assert second.observation_id == first.observation_id
    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :u AND metric_type = 'weight'
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_two_sources_colliding_record_the_disagreement_instead_of_losing_it(
    pg, two_athletes,
):
    """`ON CONFLICT DO NOTHING` used to make the loser vanish.

    "My watch and my scale disagree" is then unanswerable. The winning row is
    still the winning row — picking differently would be a selection
    decision, not an ingest one — but the rejected value is recorded.
    """
    from app.schemas.fitness_coach import Unit
    alice, _ = two_athletes
    when = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)

    kept = _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
                   recorded_at=when, source="apple_health")
    pg.commit()
    rejected = _ingest(pg, alice, metric_type="weight", value=183.2, unit=Unit.LB,
                       recorded_at=when, source="withings")
    pg.commit()

    assert kept.stored
    assert not rejected.stored
    assert rejected.conflict_recorded

    conflict = pg.execute(text(
        "SELECT source_conflict FROM health_metric WHERE id = :id"),
        {"id": kept.observation_id}).scalar()
    assert conflict and len(conflict) == 1
    assert conflict[0]["rejected_value"] == 183.2
    assert conflict[0]["rejected_source"] == "withings"
    assert conflict[0]["kept_source"] == "apple_health"


@requires_pg
def test_an_identical_repeat_from_the_same_source_is_just_a_duplicate(pg, two_athletes):
    """Corroboration is not conflict."""
    from app.schemas.fitness_coach import Unit
    alice, _ = two_athletes
    when = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
    _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
            recorded_at=when, source="apple_health")
    pg.commit()
    again = _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
                    recorded_at=when, source="apple_health")
    pg.commit()
    assert again.duplicate and not again.conflict_recorded
    assert pg.execute(text(
        "SELECT source_conflict FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar() is None


@requires_pg
def test_the_existing_dedup_index_is_untouched(pg):
    """Two live writers name it in their `ON CONFLICT` clauses.

    `routes/health_metrics.py` and `services/health_metric_mirror.py` both
    specify `(user_id, metric_type, recorded_at)`. Widening or replacing that
    index would make both fail at runtime, in the code path whose whole job
    is not to lose a sync.
    """
    definition = pg.execute(text("""
        SELECT indexdef FROM pg_indexes
        WHERE tablename = 'health_metric' AND indexname = 'ix_health_metric_dedup'
    """)).scalar()
    assert definition is not None, "the dedup index must still exist"
    assert "UNIQUE" in definition
    for column in ("user_id", "metric_type", "recorded_at"):
        assert column in definition
    assert "WHERE" not in definition, (
        "the dedup index must stay unconditional; a partial index would not "
        "satisfy the ON CONFLICT clauses that name these columns"
    )


# ─────────────────────────────────────────────────────────────────────────
# Correction
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_correction_supersedes_without_deleting(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    alice, _ = two_athletes
    wrong = _ingest(pg, alice, metric_type="weight", value=1804.0, unit=Unit.LB,
                    recorded_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC),
                    source="manual")
    pg.commit()

    right = _ingest(pg, alice, metric_type="weight", value=180.4, unit=Unit.LB,
                    recorded_at=datetime(2026, 10, 1, 11, 1, tzinfo=UTC),
                    source="manual", corrects_observation_id=wrong.observation_id,
                    correction_reason="typo: decimal point")
    pg.commit()

    assert right.superseded_id == wrong.observation_id
    old = pg.execute(text("""
        SELECT superseded_by_id, correction_reason, value FROM health_metric WHERE id = :id
    """), {"id": wrong.observation_id}).fetchone()
    assert old.superseded_by_id == right.observation_id
    assert old.correction_reason == "typo: decimal point"
    assert float(old.value) == 1804.0, "the original value is retained verbatim"


@requires_pg
def test_a_superseded_observation_is_excluded_from_selection(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import selected_series
    alice, _ = two_athletes

    wrong = _ingest(pg, alice, metric_type="weight", value=1804.0, unit=Unit.LB,
                    recorded_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC),
                    source="manual")
    _ingest(pg, alice, metric_type="weight", value=180.4, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 11, 1, tzinfo=UTC), source="manual",
            corrects_observation_id=wrong.observation_id)
    pg.commit()

    series = selected_series(pg, alice, "weight",
                            date(2026, 10, 1), date(2026, 10, 2))
    assert len(series) == 1
    assert series[date(2026, 10, 1)].value == 180.4


@requires_pg
def test_a_correction_cannot_name_another_athletes_observation(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    alice, bob = two_athletes
    bobs = _ingest(pg, bob, metric_type="weight", value=200.0, unit=Unit.LB,
                   recorded_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC), source="manual")
    pg.commit()
    with pytest.raises(LookupError):
        _ingest(pg, alice, metric_type="weight", value=150.0, unit=Unit.LB,
                recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), source="manual",
                corrects_observation_id=bobs.observation_id)
    pg.rollback()
    assert pg.execute(text(
        "SELECT superseded_by_id FROM health_metric WHERE id = :id"),
        {"id": bobs.observation_id}).scalar() is None


@requires_pg
def test_a_correction_must_be_the_same_metric_type(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.data_access import FitnessDataError
    alice, _ = two_athletes
    weight = _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
                     recorded_at=datetime(2026, 10, 1, 11, 0, tzinfo=UTC),
                     source="manual")
    pg.commit()
    with pytest.raises(FitnessDataError):
        _ingest(pg, alice, metric_type="steps", value=8000, unit=Unit.COUNT,
                recorded_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC), source="manual",
                corrects_observation_id=weight.observation_id)
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Selection rules
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_steps_take_the_daily_maximum_never_the_sum(pg, two_athletes):
    """HealthKit sends cumulative running totals.

    Summing 2000, 5500 and 9100 gives 16,600 steps for a 9,100-step day.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import DAILY_MAX, selected_series
    alice, _ = two_athletes

    for hour, total in ((9, 2000), (14, 5500), (21, 9100)):
        _ingest(pg, alice, metric_type="steps", value=total, unit=Unit.COUNT,
                recorded_at=datetime(2026, 10, 1, hour, 0, tzinfo=ET),
                source="apple_health",
                external_id=f"steps-{hour}")
    pg.commit()

    series = selected_series(pg, alice, "steps", date(2026, 10, 1), date(2026, 10, 2))
    chosen = series[date(2026, 10, 1)]
    assert chosen.value == 9100, "steps are cumulative; the day's figure is the max"
    assert chosen.value != 16600
    assert chosen.rule == str(DAILY_MAX)
    assert chosen.candidate_count == 3


@requires_pg
def test_overlapping_sleep_totals_are_one_night_not_their_sum(pg, two_athletes):
    """Two devices each reporting last night is one night."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import selected_series
    alice, _ = two_athletes

    _ingest(pg, alice, metric_type="sleep_hours", value=7.4, unit=Unit.HOUR,
            recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), source="apple_health",
            external_id="watch-night")
    _ingest(pg, alice, metric_type="sleep_duration", value=7.6, unit=Unit.HOUR,
            recorded_at=datetime(2026, 10, 1, 7, 5, tzinfo=ET), source="oura",
            external_id="ring-night")
    pg.commit()

    series = selected_series(pg, alice, "sleep_hours",
                             date(2026, 10, 1), date(2026, 10, 2))
    chosen = series[date(2026, 10, 1)]
    assert chosen.value == 7.6
    assert chosen.value < 8, "15 hours of sleep is not what happened"
    assert chosen.candidate_count == 2, "both reports are visible as candidates"


@requires_pg
def test_a_manually_confirmed_weight_outranks_a_passive_one(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import MANUAL_THEN_EARLIEST, selected_series
    alice, _ = two_athletes

    _ingest(pg, alice, metric_type="weight", value=181.0, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 30, tzinfo=ET),
            source="apple_health", external_id="scale-bt")
    _ingest(pg, alice, metric_type="weight", value=180.4, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 7, 15, tzinfo=ET), source="manual")
    pg.commit()

    chosen = selected_series(pg, alice, "weight",
                             date(2026, 10, 1), date(2026, 10, 2))[date(2026, 10, 1)]
    assert chosen.value == 180.4, "the athlete confirmed this one themselves"
    assert chosen.source == "manual"
    assert chosen.rule == str(MANUAL_THEN_EARLIEST)


@requires_pg
def test_several_passive_weighins_pick_the_earliest_not_the_mean(pg, two_athletes):
    """Three weigh-ins is not three days' worth of evidence.

    Averaging them gives a frequently-measured day extra influence over a
    weekly mean, which then reads as a trend. The earliest is also the
    comparable one: morning weight before food and water.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import selected_series
    alice, _ = two_athletes

    for hour, value in ((6, 180.0), (13, 182.8), (20, 184.2)):
        _ingest(pg, alice, metric_type="weight", value=value, unit=Unit.LB,
                recorded_at=datetime(2026, 10, 1, hour, 0, tzinfo=ET),
                source="apple_health", external_id=f"w-{hour}")
    pg.commit()

    chosen = selected_series(pg, alice, "weight",
                             date(2026, 10, 1), date(2026, 10, 2))[date(2026, 10, 1)]
    assert chosen.value == 180.0
    mean = (180.0 + 182.8 + 184.2) / 3
    assert chosen.value != pytest.approx(mean)
    assert len(chosen.alternatives) == 2, "the others stay visible"


@requires_pg
def test_disagreeing_candidates_raise_a_conflict_flag_but_agreeing_ones_do_not(
    pg, two_athletes,
):
    from app.schemas.fitness_coach import Quality, Unit
    from app.services.fitness.observations import selected_series
    alice, bob = two_athletes

    # Alice: two sources that disagree materially.
    _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 0, tzinfo=ET),
            source="apple_health", external_id="a1")
    _ingest(pg, alice, metric_type="weight", value=190.0, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 5, tzinfo=ET),
            source="withings", external_id="a2")
    # Bob: two sources that agree.
    _ingest(pg, bob, metric_type="weight", value=180.0, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 0, tzinfo=ET),
            source="apple_health", external_id="b1")
    _ingest(pg, bob, metric_type="weight", value=180.2, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 5, tzinfo=ET),
            source="withings", external_id="b2")
    pg.commit()

    a = selected_series(pg, alice, "weight",
                        date(2026, 10, 1), date(2026, 10, 2))[date(2026, 10, 1)]
    b = selected_series(pg, bob, "weight",
                        date(2026, 10, 1), date(2026, 10, 2))[date(2026, 10, 1)]
    assert Quality.SOURCE_CONFLICT in a.quality_flags
    assert Quality.SOURCE_CONFLICT not in b.quality_flags, (
        "two sources agreeing is corroboration, not conflict"
    )


@requires_pg
def test_an_unresolved_unit_is_excluded_rather_than_converted(pg, two_athletes):
    """A weight whose unit was never recorded cannot join a series."""
    from app.services.fitness.observations import selected_series
    alice, _ = two_athletes

    # Written straight to SQL, as a pre-162 row would have been.
    pg.execute(text("""
        INSERT INTO health_metric
            (id, user_id, metric_type, value, recorded_at, source, logical_date)
        VALUES (:id, :u, 'mystery_measure', 180, :ts, 'legacy', :d)
    """), {"id": str(uuid.uuid4()), "u": alice,
           "ts": datetime(2026, 10, 1, 12, 0, tzinfo=UTC), "d": date(2026, 10, 1)})
    pg.commit()

    series = selected_series(pg, alice, "mystery_measure",
                            date(2026, 10, 1), date(2026, 10, 2))
    assert series == {}, (
        "an observation with no resolvable unit must be reported as "
        "unresolved, not silently treated as the canonical unit"
    )


@requires_pg
def test_selection_groups_by_athlete_local_day_not_utc_day(pg, two_athletes):
    """A 9pm ET reading belongs to that day, not to the next UTC one."""
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import selected_series
    alice, _ = two_athletes

    # 21:30 ET on 1 October is 01:30 UTC on 2 October.
    _ingest(pg, alice, metric_type="weight", value=181.2, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 21, 30, tzinfo=ET), source="manual")
    pg.commit()

    stored = pg.execute(text("""
        SELECT logical_date, recorded_at FROM health_metric WHERE user_id = :u
    """), {"u": alice}).fetchone()
    assert stored.logical_date == date(2026, 10, 1)
    assert stored.recorded_at.astimezone(UTC).date() == date(2026, 10, 2)

    series = selected_series(pg, alice, "weight",
                            date(2026, 10, 1), date(2026, 10, 2))
    assert date(2026, 10, 1) in series


@requires_pg
def test_the_athletes_timezone_decides_the_logical_day(pg, two_athletes):
    from app.schemas.fitness_coach import AthleteProfilePatch, Unit
    from app.services.fitness.profile import patch_athlete_profile
    alice, _ = two_athletes

    patch_athlete_profile(pg, alice, AthleteProfilePatch(timezone="Asia/Tokyo"))
    # 08:00 Tokyo on 16 June is 19:00 ET on the 15th.
    _ingest(pg, alice, metric_type="weight", value=80.0, unit=Unit.KG,
            recorded_at=datetime(2026, 6, 16, 8, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            source="manual")
    pg.commit()

    logical = pg.execute(text(
        "SELECT logical_date FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar()
    assert logical == date(2026, 6, 16), (
        "the athlete's own timezone decides the day, not the server's ET default"
    )


# ─────────────────────────────────────────────────────────────────────────
# Projections
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_projections_are_built_from_the_canonical_selection(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import sync_projections
    alice, _ = two_athletes

    # A passive reading and a manual correction on the same day.
    _ingest(pg, alice, metric_type="weight", value=185.0, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 6, 0, tzinfo=ET),
            source="apple_health", external_id="p1")
    _ingest(pg, alice, metric_type="weight", value=180.4, unit=Unit.LB,
            recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), source="manual")
    pg.commit()

    touched = sync_projections(pg, alice, "weight", date(2026, 10, 1))
    pg.commit()
    assert "daily_recovery_log.body_weight" in touched
    assert "weight_trend.raw_weight" in touched

    recovery = pg.execute(text("""
        SELECT body_weight, weight_unit FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).fetchone()
    # The SELECTED value, not the first or the mean.
    assert float(recovery.body_weight) == pytest.approx(180.4)
    assert recovery.weight_unit == "lbs", (
        "the column is labelled lbs; writing a kg value into it is the bug "
        "this function exists to make impossible"
    )

    trend = pg.execute(text("""
        SELECT raw_weight FROM weight_trend WHERE user_id = :u AND date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).fetchone()
    assert float(trend.raw_weight) == pytest.approx(180.4)


@requires_pg
def test_a_kg_entry_projects_as_pounds_into_the_lbs_column(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import sync_projections
    alice, _ = two_athletes
    _ingest(pg, alice, metric_type="weight", value=82.0, unit=Unit.KG,
            recorded_at=datetime(2026, 10, 1, 7, 0, tzinfo=ET), source="manual")
    pg.commit()
    sync_projections(pg, alice, "weight", date(2026, 10, 1))
    pg.commit()
    stored = pg.execute(text("""
        SELECT body_weight, weight_unit FROM daily_recovery_log
        WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).fetchone()
    assert float(stored.body_weight) == pytest.approx(180.78, abs=0.02)
    assert stored.weight_unit == "lbs"


@requires_pg
def test_a_backdated_correction_rebuilds_every_later_trend_value(pg, two_athletes):
    """Each EWMA value was computed from the series as it then stood.

    Correcting a reading in the middle invalidates all of them, and leaving
    them means the displayed trend no longer follows from the observations.
    """
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation, rebuild_weight_trend
    alice, _ = two_athletes

    days = [date(2026, 9, 20) + timedelta(days=i) for i in range(6)]
    for i, day in enumerate(days):
        _ingest(pg, alice, metric_type="weight", value=180.0 + i * 0.2, unit=Unit.LB,
                recorded_at=datetime.combine(day, datetime.min.time(), tzinfo=ET)
                            .replace(hour=7),
                source="manual")
    pg.commit()
    rebuild_weight_trend(pg, alice, from_date=days[0])
    pg.commit()

    before = {
        r.date: float(r.trend_weight) for r in pg.execute(text("""
            SELECT date, trend_weight FROM weight_trend WHERE user_id = :u
        """), {"u": alice}).fetchall()
    }
    assert len(before) == 6

    # The third day's reading was wrong by 10 lb.
    wrong = pg.execute(text("""
        SELECT id FROM health_metric
        WHERE user_id = :u AND logical_date = :d AND metric_type = 'weight'
    """), {"u": alice, "d": days[2]}).scalar()
    ingest_observation(
        pg, alice, metric_type="weight", value=170.4, unit=Unit.LB,
        recorded_at=datetime.combine(days[2], datetime.min.time(), tzinfo=ET)
                    .replace(hour=8),
        source="manual", corrects_observation_id=wrong,
        correction_reason="read the wrong scale",
    )
    pg.commit()
    rebuild_weight_trend(pg, alice, from_date=days[2])
    pg.commit()

    after = {
        r.date: float(r.trend_weight) for r in pg.execute(text("""
            SELECT date, trend_weight FROM weight_trend WHERE user_id = :u
        """), {"u": alice}).fetchall()
    }
    assert after[days[0]] == before[days[0]], "days before the correction are untouched"
    assert after[days[1]] == before[days[1]]
    for day in days[2:]:
        assert after[day] != before[day], (
            f"{day}'s trend value was computed from the uncorrected series"
        )
    assert float(pg.execute(text("""
        SELECT raw_weight FROM weight_trend WHERE user_id = :u AND date = :d
    """), {"u": alice, "d": days[2]}).scalar()) == pytest.approx(170.4)


# ─────────────────────────────────────────────────────────────────────────
# Every writer uses the shared ingest
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_ios_batch_endpoint_writes_units_and_logical_dates(pg, two_athletes):
    """`/api/health/metrics/batch` is the main ingest path.

    The response contract is unchanged — the shipped iOS build reads
    `inserted_count`/`duplicate_count` — but the rows it writes now carry
    units, provenance and an athlete-local logical date.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.health_metrics import router

    alice, _ = two_athletes
    app = FastAPI()
    # The router declares `prefix="/api/health"` itself — mounting it with
    # the prefix again would serve it at /api/health/api/health.
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.post("/api/health/metrics/batch", headers=headers, json={
        "metrics": [
            {"metric_type": "weight", "value": 181.2,
             "recorded_at": "2026-10-01T11:00:00+00:00", "source": "apple_health"},
            {"metric_type": "steps", "value": 9100,
             "recorded_at": "2026-10-01T23:00:00+00:00", "source": "apple_health"},
            # A NaN-shaped null, which HealthKit does send.
            {"metric_type": "hrv", "value": None,
             "recorded_at": "2026-10-01T11:00:00+00:00", "source": "apple_health"},
        ]
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted_count"] == 2
    assert body["skipped_invalid"] == 1
    assert "duplicate_count" in body and "daily_recovery_updated" in body

    rows = pg.execute(text("""
        SELECT metric_type, unit, logical_date, source_quality
        FROM health_metric WHERE user_id = :u ORDER BY metric_type
    """), {"u": alice}).fetchall()
    assert len(rows) == 2
    by_type = {r.metric_type: r for r in rows}
    assert by_type["weight"].unit == "lb"
    assert by_type["steps"].unit == "count"
    assert by_type["weight"].logical_date is not None
    assert by_type["weight"].source_quality == "measured"


@requires_pg
def test_the_batch_endpoint_is_idempotent_with_sample_ids(pg, two_athletes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.health_metrics import router

    alice, _ = two_athletes
    app = FastAPI()
    # The router declares `prefix="/api/health"` itself — mounting it with
    # the prefix again would serve it at /api/health/api/health.
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}
    payload = {
        "metrics": [{
            "metric_type": "weight", "value": 181.2,
            "recorded_at": "2026-10-01T11:00:00+00:00", "source": "apple_health",
            "external_id": "HK-SAMPLE-1",
        }]
    }
    first = client.post("/api/health/metrics/batch", headers=headers, json=payload)
    second = client.post("/api/health/metrics/batch", headers=headers, json=payload)
    assert first.json()["inserted_count"] == 1
    assert second.json()["inserted_count"] == 0
    assert second.json()["duplicate_count"] == 1
    assert pg.execute(text(
        "SELECT COUNT(*) FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar() == 1


@requires_pg
def test_the_batch_endpoint_rejects_an_unrecognised_unit_rather_than_reinterpreting(
    pg, two_athletes,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.health_metrics import router

    alice, _ = two_athletes
    app = FastAPI()
    # The router declares `prefix="/api/health"` itself — mounting it with
    # the prefix again would serve it at /api/health/api/health.
    app.include_router(router)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    r = client.post("/api/health/metrics/batch", headers=headers, json={
        "metrics": [{
            "metric_type": "weight", "value": 13.0, "unit": "stones",
            "recorded_at": "2026-10-01T11:00:00+00:00", "source": "apple_health",
        }]
    })
    assert r.status_code == 200
    assert r.json()["skipped_invalid"] == 1
    assert r.json()["inserted_count"] == 0
    assert pg.execute(text(
        "SELECT COUNT(*) FROM health_metric WHERE user_id = :u"), {"u": alice}
    ).scalar() == 0, "13 stones must not be stored as 13 pounds"


@requires_pg
def test_the_web_weight_form_creates_a_canonical_observation(pg, two_athletes):
    """It used to write ONLY `weight_trend`.

    A weight typed into the web app therefore never became a canonical
    observation, so the Coach, the weekly health report and the iOS app each
    saw a different set of weigh-ins depending on which table they read.
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

    r = client.post("/api/fitness/weight", headers=headers,
                    json={"date": "2026-10-01", "raw_weight": 181.6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["raw_weight"] == pytest.approx(181.6)
    assert "trend_weight" in body and "weekly_delta" in body

    observation = pg.execute(text("""
        SELECT value, unit, source, source_quality, logical_date, metadata
        FROM health_metric WHERE user_id = :u AND metric_type = 'weight'
    """), {"u": alice}).fetchone()
    assert observation is not None, "the web form left no canonical observation"
    assert float(observation.value) == pytest.approx(181.6)
    assert observation.unit == "lb"
    assert observation.source == "manual"
    assert observation.source_quality == "manual", (
        "the 07:00 stamp was chosen by the app, not measured"
    )
    assert observation.logical_date == date(2026, 10, 1)

    trend = pg.execute(text("""
        SELECT raw_weight FROM weight_trend WHERE user_id = :u AND date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).fetchone()
    assert float(trend.raw_weight) == pytest.approx(181.6)


@requires_pg
def test_the_recovery_card_mirrors_weight_sleep_and_resting_hr(pg, two_athletes):
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
        "log_date": "2026-10-01", "hrv": 68, "heart_rate": 52,
        "sleep_hours": 7.25, "soreness_level": 3,
        "body_weight": 181.0, "weight_unit": "lbs",
    })
    assert r.status_code == 200, r.text

    stored = {
        row.metric_type: float(row.value) for row in pg.execute(text("""
            SELECT metric_type, value FROM health_metric WHERE user_id = :u
        """), {"u": alice}).fetchall()
    }
    assert stored.get("weight") == pytest.approx(181.0)
    assert stored.get("sleep_hours") == pytest.approx(7.25)
    assert stored.get("resting_heart_rate") == pytest.approx(52.0)
    assert "hrv_morning" in stored, "HRV keeps its existing dedicated mirror"

    # The recovery row itself is unchanged in shape.
    recovery = pg.execute(text("""
        SELECT hrv, heart_rate, sleep_hours, soreness_level, body_weight, weight_unit
        FROM daily_recovery_log WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).fetchone()
    assert recovery.hrv == 68
    assert recovery.soreness_level == 3


@requires_pg
def test_a_recovery_card_entry_in_kg_is_stored_as_pounds(pg, two_athletes):
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
        "log_date": "2026-10-01", "body_weight": 82.0, "weight_unit": "kg",
    })
    assert r.status_code == 200, r.text
    observation = pg.execute(text("""
        SELECT value, unit, original_value, original_unit
        FROM health_metric WHERE user_id = :u AND metric_type = 'weight'
    """), {"u": alice}).fetchone()
    assert observation.unit == "lb"
    assert float(observation.value) == pytest.approx(180.78, abs=0.02)
    assert float(observation.original_value) == 82.0
    assert observation.original_unit == "kg"


@requires_pg
def test_a_failed_mirror_does_not_lose_the_recovery_row(pg, two_athletes, monkeypatch):
    """The real write is the user's request; the mirror is derived.

    A mirror that raised used to be able to poison the transaction and take
    the recovery row with it, which turns a successful entry into a 500.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import create_access_token
    from app.routes.fitness import router
    import app.services.fitness.observations as obs

    alice, _ = two_athletes
    app = FastAPI()
    app.include_router(router, prefix="/api/fitness")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': alice})}"}

    def boom(*args, **kwargs):
        raise RuntimeError("mirror exploded")

    monkeypatch.setattr(obs, "ingest_observation", boom)

    r = client.post("/api/fitness/recovery", headers=headers, json={
        "log_date": "2026-10-01", "hrv": 70, "sleep_hours": 7.0, "body_weight": 180.0,
    })
    assert r.status_code == 200, r.text
    assert pg.execute(text("""
        SELECT COUNT(*) FROM daily_recovery_log WHERE user_id = :u AND log_date = :d
    """), {"u": alice, "d": date(2026, 10, 1)}).scalar() == 1


@requires_pg
def test_observations_do_not_cross_between_athletes(pg, two_athletes):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import latest_metric, selected_series
    alice, bob = two_athletes

    _ingest(pg, alice, metric_type="weight", value=180.0, unit=Unit.LB,
            recorded_at=datetime.now(UTC) - timedelta(hours=1), source="manual")
    _ingest(pg, bob, metric_type="weight", value=220.0, unit=Unit.LB,
            recorded_at=datetime.now(UTC) - timedelta(hours=1), source="manual")
    pg.commit()

    assert latest_metric(pg, alice, "weight").value == 180.0
    assert latest_metric(pg, bob, "weight").value == 220.0


@requires_pg
def test_latest_metric_says_unknown_rather_than_nothing(pg, two_athletes):
    from app.schemas.fitness_coach import Unavailable
    from app.services.fitness.observations import latest_metric
    alice, _ = two_athletes
    metric = latest_metric(pg, alice, "weight")
    assert metric.value is None
    assert metric.unavailable_reason is Unavailable.NO_DATA
