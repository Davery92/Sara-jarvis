"""Step 3 of FITNESS_COACH_IMPLEMENTATION_PLAN: the normalization layer can
read Sara's existing fitness rows honestly, including the ones whose units
were never recorded.

Pure units — no database, no Redis, no LLM. That is itself part of the
contract being asserted: `import app.services.fitness.data_access` must not
open a connection, and these adapters must be usable from a Celery task, a
route and a test with the same result.

The fixtures here are hand-derived. A test that recomputes the function under
test proves only that the function is deterministic.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.schemas.fitness_coach import (
    UNSET,
    AthleteGoalIn,
    AthleteProfilePatch,
    CheckInPatch,
    GoalKind,
    MeasurementIn,
    Metric,
    Period,
    Quality,
    RateBasis,
    Side,
    TargetValues,
    Unavailable,
    Unit,
    UnitError,
    convert,
    ensure_finite,
    normalize_code,
    present_fields,
    round_display,
    to_kg,
    validate_scale,
)
from app.services.fitness import data_access as da

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────
# Unit conversion and precision
# ─────────────────────────────────────────────────────────────────────────

def test_kg_lb_roundtrip_keeps_quarter_kilo_steps():
    """A 0.25 kg / 2.5 lb change must survive the trip, not round away."""
    for kg in (80.0, 80.25, 80.5, 102.75):
        lb = convert(kg, Unit.KG, Unit.LB)
        back = convert(lb, Unit.LB, Unit.KG)
        assert abs(back - kg) < 1e-9, f"{kg} kg did not round-trip"


def test_known_conversions_against_hand_values():
    assert round(convert(1, Unit.KG, Unit.LB), 5) == 2.20462
    assert round(convert(100, Unit.LB, Unit.KG), 4) == 45.3592
    assert round(convert(70, Unit.INCH, Unit.CM), 2) == 177.80
    assert convert(1, Unit.HOUR, Unit.MINUTE) == 60
    assert convert(90, Unit.SECOND, Unit.MINUTE) == 1.5


def test_unknown_unit_refuses_to_be_guessed():
    """The magnitude of a bodyweight does not disclose its unit.

    180 lb and 180 kg are both real human bodyweights. A helper that picked
    one would silently misstate a 40%-different number.
    """
    with pytest.raises(UnitError) as e:
        convert(180, Unit.UNKNOWN, Unit.KG)
    assert "not inferable from the magnitude" in str(e.value)


def test_incompatible_quantities_refuse():
    with pytest.raises(UnitError):
        convert(80, Unit.KG, Unit.CM)


def test_nan_and_infinity_are_rejected_at_the_boundary():
    """One NaN poisons every aggregate it reaches and survives == filtering."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(UnitError):
            ensure_finite(bad, "weight")
    assert ensure_finite(None) is None
    assert ensure_finite(0.0) == 0.0


def test_rounding_is_display_only():
    assert round_display(81.2449, 1) == 81.2
    assert round_display(81.25, 1) == 81.3
    assert round_display(None) is None
    # The analytics value itself keeps precision: 102.5 / 2.20462262185.
    assert to_kg(102.5, Unit.LB) == pytest.approx(46.49322, abs=1e-5)
    assert round_display(to_kg(102.5, Unit.LB), 1) == 46.5


# ─────────────────────────────────────────────────────────────────────────
# Metric: unknown vs zero vs rejected
# ─────────────────────────────────────────────────────────────────────────

def test_zero_is_a_value_and_none_is_not():
    """Nobody ate zero calories; they did not log. These cannot be one value."""
    logged_nothing = Metric(key="nutrition.calories_mean", value=None,
                            unavailable_reason=Unavailable.NO_DATA)
    genuinely_zero = Metric(key="training.working_sets", value=0.0, unit=Unit.COUNT)

    assert logged_nothing.value is None
    assert genuinely_zero.value == 0.0
    assert logged_nothing.unavailable_reason is Unavailable.NO_DATA
    assert genuinely_zero.unavailable_reason is None


def test_absent_metric_must_explain_itself():
    with pytest.raises(Exception) as e:
        Metric(key="weight.velocity", value=None)
    assert "unavailable_reason" in str(e.value)


def test_metric_coverage_reports_the_real_denominator():
    m = Metric(key="weight.mean_7d", value=81.1, unit=Unit.KG,
               observed_days=3, expected_days=7,
               period=Period(start=date(2026, 9, 24), end=date(2026, 10, 1)))
    assert m.coverage == pytest.approx(3 / 7)
    assert m.period.days == 7
    # Coverage is None, not 1.0, when nobody said what was expected.
    assert Metric(key="x", value=1.0).coverage is None


def test_period_is_half_open_and_ordered():
    p = Period(start=date(2026, 9, 24), end=date(2026, 10, 1))
    assert p.contains(date(2026, 9, 24))
    assert not p.contains(date(2026, 10, 1)), "end must be exclusive"
    with pytest.raises(Exception):
        Period(start=date(2026, 10, 1), end=date(2026, 9, 24))


# ─────────────────────────────────────────────────────────────────────────
# Athlete-local dates, DST, midnight
# ─────────────────────────────────────────────────────────────────────────

def test_dst_days_are_not_24_hours():
    """`start + 24h` is the bug that duplicates or drops a boundary reading."""
    spring_start, spring_end = da.local_day_bounds(date(2026, 3, 8), ET)
    fall_start, fall_end = da.local_day_bounds(date(2026, 11, 1), ET)
    assert spring_end - spring_start == timedelta(hours=23)
    assert fall_end - fall_start == timedelta(hours=25)


def test_midnight_boundary_belongs_to_exactly_one_day():
    start, end = da.local_day_bounds(date(2026, 6, 15), ET)
    just_before = start - timedelta(microseconds=1)
    exactly_midnight = start
    assert da.local_date_of(just_before, ET) == date(2026, 6, 14)
    assert da.local_date_of(exactly_midnight, ET) == date(2026, 6, 15)
    assert da.local_date_of(end, ET) == date(2026, 6, 16)


def test_travelling_athlete_gets_their_own_day():
    """08:00 in Tokyo on the 16th is 19:00 ET on the 15th."""
    tokyo = ZoneInfo("Asia/Tokyo")
    moment = datetime(2026, 6, 16, 8, 0, tzinfo=tokyo)
    assert da.local_date_of(moment, tokyo) == date(2026, 6, 16)
    assert da.local_date_of(moment, ET) == date(2026, 6, 15)


def test_the_three_timestamp_conventions_convert_distinctly():
    """food_log.logged_at is naive ET; created_at is naive UTC."""
    naive = datetime(2026, 6, 15, 21, 30)
    as_et = da.naive_et_to_utc(naive)
    as_utc = da.naive_utc_to_utc(naive)
    assert as_et == datetime(2026, 6, 16, 1, 30, tzinfo=UTC)
    assert as_utc == datetime(2026, 6, 15, 21, 30, tzinfo=UTC)
    assert as_et != as_utc, "collapsing the two conventions shifts meals by 4-5h"
    # A 9:30pm ET dinner stays on the 15th for an ET athlete.
    assert da.local_date_of(as_et, ET) == date(2026, 6, 15)


def test_aware_column_helper_refuses_a_naive_value():
    """Reaching this helper with a naive value means the wrong adapter was used."""
    with pytest.raises(da.FitnessDataError):
        da.as_aware_utc(datetime(2026, 6, 15, 12, 0))


def test_span_and_page_bounds():
    with pytest.raises(da.FitnessDataError):
        da.validate_span(date(2026, 6, 2), date(2026, 6, 1))
    with pytest.raises(da.FitnessDataError):
        da.validate_span(date(2020, 1, 1), date(2026, 1, 1))
    assert da.validate_page_size(None) == da.DEFAULT_PAGE_SIZE
    assert da.validate_page_size(10_000) == da.MAX_PAGE_SIZE
    with pytest.raises(da.FitnessDataError):
        da.validate_page_size(0)


def test_unknown_timezone_falls_back_without_breaking_a_read():
    assert da.athlete_zone("Mars/Olympus_Mons") is not None
    assert da.athlete_zone(None) is not None


# ─────────────────────────────────────────────────────────────────────────
# Legacy row adapters
# ─────────────────────────────────────────────────────────────────────────

def test_effective_load_prefers_the_fractional_column():
    """`workout_log.weight` is an INTEGER — it has already lost the fraction.

    Reading it first turns every 102.5 lb set into 102 lb, and that rounding
    looks exactly like a plateau to a trend calculation.
    """
    both = {"load_value": 102.5, "load_unit": "lb", "weight": 102}
    assert da.effective_load(both) == (102.5, Unit.LB)

    legacy_only = {"weight": 102}
    assert da.effective_load(legacy_only) == (102.0, Unit.LB)

    neither = {"weight": None}
    assert da.effective_load(neither) == (None, Unit.UNKNOWN)


def test_effective_load_respects_a_metric_unit():
    assert da.effective_load({"load_value": 47.5, "load_unit": "kg"}) == (47.5, Unit.KG)


def test_legacy_metric_units_come_from_traced_writers_not_magnitudes():
    assert da.resolve_metric_unit("weight", None) is Unit.LB
    assert da.resolve_metric_unit("sleep_hours", None) is Unit.HOUR
    assert da.resolve_metric_unit("steps", None) is Unit.COUNT
    # Stored unit wins over the legacy default.
    assert da.resolve_metric_unit("weight", "kg") is Unit.KG
    # An unrecognised stored unit is a conflict to surface, not to fix up.
    assert da.resolve_metric_unit("weight", "stones") is Unit.UNKNOWN
    # A type nobody traced is unknown, not assumed.
    assert da.resolve_metric_unit("grip_strength", None) is Unit.UNKNOWN


def test_json_and_text_template_columns_parse_identically():
    """`fitness_template.exercises` is TEXT holding JSON; snapshots are JSONB."""
    as_text = '[{"name": "Bench Press", "sets": 3}]'
    as_obj = [{"name": "Bench Press", "sets": 3}]
    assert da.parse_json_column(as_text) == da.parse_json_column(as_obj) == as_obj
    assert da.parse_json_column(None) == {}
    assert da.parse_json_column("") == {}
    assert da.parse_json_column("{not json") == {}


def test_set_row_adapter_classifies_live_working_sets():
    base = {
        "id": "s1", "user_id": "u1", "exercise_id": "Bench Press",
        "exercise_library_id": None, "set_index": 1, "reps": 5,
        "weight": 225, "rpe": 8, "set_kind": "working",
        "parent_set_id": None, "set_group_id": None, "group_sequence": 0,
        "counts_toward_target": True, "voided_at": None, "skipped": False,
        "active_session_id": "a1", "session_id": None,
        "session_date": date(2026, 9, 30), "session_time": None,
        "created_at": datetime(2026, 9, 30, 15, 0),
        "is_pr": False,
    }

    class _Row:
        def __init__(self, m):
            self._mapping = m

    live = da.adapt_set_row(_Row(dict(base)), tz=ET)
    assert live.is_live and live.is_working
    assert live.load == 225.0 and live.load_unit is Unit.LB

    voided = da.adapt_set_row(
        _Row({**base, "voided_at": datetime(2026, 9, 30, 16, 0, tzinfo=UTC)}), tz=ET)
    assert not voided.is_live, "a voided set must never count as performed"

    skipped = da.adapt_set_row(_Row({**base, "skipped": True}), tz=ET)
    assert not skipped.is_live

    warmup = da.adapt_set_row(_Row({**base, "set_kind": "warmup"}), tz=ET)
    assert warmup.is_live and not warmup.is_working

    fractional = da.adapt_set_row(
        _Row({**base, "load_value": 227.5, "load_unit": "lb"}), tz=ET)
    assert fractional.load == 227.5


def test_set_row_load_kg_is_none_for_an_unknown_unit():
    class _Row:
        def __init__(self, m):
            self._mapping = m

    r = da.adapt_set_row(_Row({
        "id": "s", "user_id": "u", "exercise_id": "x", "exercise_library_id": None,
        "set_index": 1, "reps": 5, "weight": None, "rpe": None,
        "set_kind": "working", "parent_set_id": None, "set_group_id": None,
        "group_sequence": 0, "counts_toward_target": True, "voided_at": None,
        "skipped": False, "active_session_id": None, "session_id": None,
        "session_date": None, "session_time": None, "created_at": None,
        "is_pr": False,
    }), tz=ET)
    assert r.load_kg is None, "an unknown unit must not become a silent kilogram"


# ─────────────────────────────────────────────────────────────────────────
# Owner scope
# ─────────────────────────────────────────────────────────────────────────

def test_no_helper_has_a_default_owner():
    """The Step 2 bug, as a unit test on the layer that replaced it."""
    for bad in (None, "", "   "):
        with pytest.raises(da.FitnessDataError) as e:
            da._require_user(bad)
        assert "no default owner" in str(e.value)


def test_assert_owned_refuses_an_arbitrary_table_name():
    """A measurement or tool parameter must not be able to name a table."""
    class _FakeDB:
        def execute(self, *a, **kw):
            raise AssertionError("must not reach SQL with an unvetted table")

    with pytest.raises(da.FitnessDataError):
        da.assert_owned(_FakeDB(), "u1", "app_user; DROP TABLE x", "id")
    with pytest.raises(da.FitnessDataError):
        da.assert_owned(_FakeDB(), "u1", "revoked_token", "id")
    with pytest.raises(da.FitnessDataError):
        da.assert_owned(_FakeDB(), "u1", "fitness_template", "id",
                        owner_column="1=1")
    # A None id is a no-op, not an error: an optional parent is optional.
    da.assert_owned(_FakeDB(), "u1", "fitness_template", None)


# ─────────────────────────────────────────────────────────────────────────
# Omitted vs explicitly cleared
# ─────────────────────────────────────────────────────────────────────────

def test_patch_distinguishes_omitted_from_cleared():
    """Without this, a PATCH either wipes untouched fields or cannot clear one."""
    omitted = CheckInPatch(energy=7)
    assert present_fields(omitted) == {"energy": 7}
    assert "soreness_level" not in present_fields(omitted)

    cleared = CheckInPatch(energy=7, soreness_level=None)
    fields = present_fields(cleared)
    assert fields["soreness_level"] is None
    assert "soreness_level" in fields, "an explicit null must be visible as a clear"


def test_control_fields_are_not_patchable_columns():
    p = CheckInPatch(energy=5, expected_version=3, idempotency_key="k")
    assert present_fields(p) == {"energy": 5}


def test_patch_rejects_unknown_fields():
    with pytest.raises(Exception):
        CheckInPatch(not_a_field=1)


def test_scale_validation_and_documented_directions():
    assert validate_scale("energy", 7) == 7
    assert validate_scale("energy", None) is None
    for bad in (0, 11, -1):
        with pytest.raises(ValueError):
            validate_scale("energy", bad)
    with pytest.raises(ValueError):
        validate_scale("vibes", 5)

    from app.schemas.fitness_coach import SCALE_DIRECTIONS
    assert SCALE_DIRECTIONS["soreness_level"] == "lower_is_better"
    assert SCALE_DIRECTIONS["energy"] == "higher_is_better"


def test_sleep_episode_sanity():
    with pytest.raises(Exception):
        CheckInPatch(bedtime_at=datetime(2026, 6, 15, 23, 0),
                     wake_at=datetime(2026, 6, 15, 22, 0))
    with pytest.raises(Exception):
        CheckInPatch(bedtime_at=datetime(2026, 6, 15, 23, 0),
                     wake_at=datetime(2026, 6, 17, 23, 30))
    ok = CheckInPatch(bedtime_at=datetime(2026, 6, 15, 23, 0),
                      wake_at=datetime(2026, 6, 16, 7, 0))
    assert present_fields(ok)["wake_at"].hour == 7


def test_profile_patch_validates_without_inventing_defaults():
    with pytest.raises(Exception):
        AthleteProfilePatch(height_cm=12)
    with pytest.raises(Exception):
        AthleteProfilePatch(timezone="Nowhere/Nothing")
    with pytest.raises(Exception):
        AthleteProfilePatch(training_experience_years=120)
    # Unknown sex and absent DOB are permanently valid answers.
    p = AthleteProfilePatch(calculation_sex="prefer_not_to_say")
    assert present_fields(p) == {"calculation_sex": "prefer_not_to_say"}
    assert present_fields(AthleteProfilePatch()) == {}


# ─────────────────────────────────────────────────────────────────────────
# Goal and target coherence
# ─────────────────────────────────────────────────────────────────────────

def test_goal_rate_sign_must_match_its_direction():
    with pytest.raises(Exception):
        AthleteGoalIn(kind=GoalKind.CUT, rate_basis=RateBasis.ABSOLUTE,
                      target_rate_kg_week=0.25, valid_from=date(2026, 10, 1))
    with pytest.raises(Exception):
        AthleteGoalIn(kind=GoalKind.GAIN, rate_basis=RateBasis.ABSOLUTE,
                      target_rate_kg_week=-0.25, valid_from=date(2026, 10, 1))
    ok = AthleteGoalIn(kind=GoalKind.CUT, rate_basis=RateBasis.ABSOLUTE,
                       target_rate_kg_week=-0.4, valid_from=date(2026, 10, 1))
    assert ok.target_rate_kg_week == -0.4


def test_goal_rate_basis_must_be_explicit():
    """Storing both rate fields makes the athlete's actual choice unknowable."""
    with pytest.raises(Exception):
        AthleteGoalIn(kind=GoalKind.GAIN, rate_basis=RateBasis.NONE,
                      target_rate_kg_week=0.25, valid_from=date(2026, 10, 1))
    with pytest.raises(Exception):
        AthleteGoalIn(kind=GoalKind.GAIN, rate_basis=RateBasis.PERCENT,
                      valid_from=date(2026, 10, 1))


def test_goal_interval_is_half_open():
    with pytest.raises(Exception):
        AthleteGoalIn(kind=GoalKind.MAINTENANCE, valid_from=date(2026, 10, 1),
                      valid_until=date(2026, 10, 1))


def test_target_values_bound_absurd_numbers():
    ok = TargetValues(calories=3200, protein_g=200)
    assert ok.calories == 3200
    assert ok.carbs_g is None, "an unset macro stays unknown, not zero"
    with pytest.raises(Exception):
        TargetValues(calories=-1)
    with pytest.raises(Exception):
        TargetValues(protein_g=99999)


# ─────────────────────────────────────────────────────────────────────────
# Measurements
# ─────────────────────────────────────────────────────────────────────────

def test_measurement_requires_a_unit_and_a_positive_finite_value():
    ok = MeasurementIn(type_code="waist_circumference", value=81.5, unit=Unit.CM,
                       measured_at=datetime(2026, 10, 1, 7, 0, tzinfo=UTC),
                       side=Side.NONE)
    assert ok.value == 81.5
    with pytest.raises(Exception):
        MeasurementIn(type_code="waist_circumference", value=0, unit=Unit.CM,
                      measured_at=datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(Exception):
        MeasurementIn(type_code="waist_circumference", value=-3, unit=Unit.CM,
                      measured_at=datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(Exception):
        MeasurementIn(type_code="waist_circumference", value=81.5,
                      unit=Unit.UNKNOWN,
                      measured_at=datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(Exception):
        MeasurementIn(type_code="w", value=float("nan"), unit=Unit.CM,
                      measured_at=datetime(2026, 10, 1, tzinfo=UTC))


def test_code_normalization_is_one_function():
    """Measurement codes and exercise aliases must not diverge."""
    assert normalize_code("BB  Bench-Press!") == "bb_bench_press"
    assert normalize_code("  Waist Circumference ") == "waist_circumference"
    assert normalize_code("waist_circumference") == "waist_circumference"
    assert normalize_code("!!!") == ""
