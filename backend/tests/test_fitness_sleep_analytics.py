"""Step 15 of FITNESS_COACH_IMPLEMENTATION_PLAN: sleep analytics, against
hand-derived fixtures.

The claim that produces most of the code: **bedtimes need circular
statistics.** 23:50 and 00:10 are 20 minutes apart. Linear arithmetic on
minutes-past-midnight makes them 1420 and 10 — 23 hours 40 apart — and
reports an athlete with an unusually regular bedtime as wildly erratic.
That is not a rounding error; it inverts the finding.

The others:

* A missing night is not zero hours of sleep.
* The computed readiness score is not the athlete's own answer.
* Subjective scales need their direction stated, or "soreness improved" and
  "soreness increased" are the same number moving.
"""
import math
from datetime import date, timedelta

import pytest

from app.schemas.fitness_coach import Unavailable, Unit
from app.services.fitness.analytics import (
    MIN_NIGHTS_FOR_SLEEP,
    DailyValue,
    SleepNight,
    sleep_metrics,
    subjective_metrics,
)

AS_OF = date(2026, 10, 1)


def days_before(n: int) -> date:
    return AS_OF - timedelta(days=n)


def night(offset: int, hours=None, bed=None, wake=None, quality=None) -> SleepNight:
    return SleepNight(
        day=days_before(offset), hours=hours,
        bedtime_minutes=bed, wake_minutes=wake, quality=quality,
    )


def clock(hour: int, minute: int = 0) -> int:
    """Minutes past midnight."""
    return hour * 60 + minute


# ── Duration ──────────────────────────────────────────────────────────────

def test_the_nightly_mean_is_hand_checkable():
    nights = [night(n, hours=h) for n, h in
              ((6, 7.5), (5, 6.75), (4, 8.0), (3, 7.25))]
    group = sleep_metrics(nights, AS_OF)
    mean = group.metrics["duration_mean"]
    assert mean.value == pytest.approx((7.5 + 6.75 + 8.0 + 7.25) / 4)
    assert mean.unit is Unit.HOUR
    assert mean.observed_days == 4
    assert mean.expected_days == 7


def test_a_missing_night_is_not_zero_hours_of_sleep():
    """Three nights recorded out of seven.

    Dividing by seven reports 3.2 hours a night for someone averaging 7.5,
    which would read as severe deprivation.
    """
    nights = [night(n, hours=7.5) for n in (6, 4, 2)]
    group = sleep_metrics(nights, AS_OF)
    mean = group.metrics["duration_mean"]
    assert mean.value == pytest.approx(7.5)
    assert mean.value != pytest.approx(3 * 7.5 / 7)
    assert group.metrics["nights_observed"].value == 3.0
    assert mean.expected_days == 7


def test_too_few_nights_gives_no_mean():
    nights = [night(6, hours=7.5), night(5, hours=7.0)]
    group = sleep_metrics(nights, AS_OF)
    mean = group.metrics["duration_mean"]
    assert mean.value is None
    assert mean.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert str(MIN_NIGHTS_FOR_SLEEP) in (mean.note or "")
    # The count is still reported: two nights is a fact.
    assert group.metrics["nights_observed"].value == 2.0


def test_a_night_with_no_duration_is_excluded_from_the_mean():
    nights = [
        night(6, hours=7.5), night(5, hours=7.0), night(4, hours=8.0),
        night(3, hours=None, bed=clock(23, 30)),   # bedtime but no total
    ]
    group = sleep_metrics(nights, AS_OF)
    assert group.metrics["duration_mean"].observed_days == 3
    assert group.metrics["duration_mean"].value == pytest.approx(
        (7.5 + 7.0 + 8.0) / 3
    )


def test_deviation_from_target_is_the_mean_minus_the_target():
    nights = [night(n, hours=6.5) for n in (6, 5, 4, 3)]
    group = sleep_metrics(nights, AS_OF, target_hours=8.0)
    deviation = group.metrics["deviation_from_target"]
    assert deviation.value == pytest.approx(-1.5)
    assert deviation.unit is Unit.HOUR


def test_no_sleep_target_means_no_deviation_figure():
    nights = [night(n, hours=7.5) for n in (6, 5, 4)]
    group = sleep_metrics(nights, AS_OF)
    deviation = group.metrics["deviation_from_target"]
    assert deviation.value is None
    assert deviation.unavailable_reason is Unavailable.NO_TARGET


def test_no_mean_means_no_deviation_even_with_a_target():
    group = sleep_metrics([night(6, hours=7.5)], AS_OF, target_hours=8.0)
    assert group.metrics["deviation_from_target"].value is None


def test_duration_variability_needs_two_nights():
    assert sleep_metrics([night(6, hours=7.5)], AS_OF) \
        .metrics["duration_variability"].value is None

    nights = [night(n, hours=h) for n, h in ((6, 7.0), (5, 8.0))]
    variability = sleep_metrics(nights, AS_OF).metrics["duration_variability"]
    # Sample stdev of [7, 8] is 1/sqrt(2).
    assert variability.value == pytest.approx(1 / math.sqrt(2))
    assert variability.unit is Unit.HOUR


# ── Circular clock arithmetic ─────────────────────────────────────────────

def test_bedtimes_either_side_of_midnight_average_to_midnight():
    """The failure this exists to prevent.

    Linear arithmetic on 1430 and 10 minutes gives a mean of 720 — midday —
    for someone who goes to bed at midnight.
    """
    nights = [
        night(6, hours=7.5, bed=clock(23, 50)),
        night(5, hours=7.5, bed=clock(0, 10)),
        night(4, hours=7.5, bed=clock(23, 55)),
        night(3, hours=7.5, bed=clock(0, 5)),
    ]
    group = sleep_metrics(nights, AS_OF)
    mean_clock = group.metrics["bedtime_mean_clock"]
    assert mean_clock.value is not None
    # Within a couple of minutes of midnight, either just before or just
    # after — never midday.
    distance_from_midnight = min(mean_clock.value, 1440 - mean_clock.value)
    assert distance_from_midnight < 3, f"got {mean_clock.value} minutes"
    linear_mean = (clock(23, 50) + clock(0, 10) + clock(23, 55) + clock(0, 5)) / 4
    assert abs(linear_mean - 720) < 1, "sanity: the linear mean really is midday"
    assert distance_from_midnight < 100


def test_a_regular_bedtime_across_midnight_reads_as_consistent():
    """23:50 and 00:10 are 20 minutes apart, not 23 hours 40.

    Linear arithmetic would report this athlete as the most erratic sleeper
    in the data.
    """
    nights = [
        night(6, hours=7.5, bed=clock(23, 50)),
        night(5, hours=7.5, bed=clock(0, 10)),
        night(4, hours=7.5, bed=clock(23, 55)),
        night(3, hours=7.5, bed=clock(0, 5)),
    ]
    consistency = sleep_metrics(nights, AS_OF).metrics["bedtime_consistency"]
    assert consistency.value is not None
    assert consistency.unit is Unit.MINUTE
    # A spread of minutes, not of hours.
    assert consistency.value < 30, f"got {consistency.value} minutes of spread"
    assert "20 minutes apart" in (consistency.note or "")


def test_a_genuinely_erratic_bedtime_reads_as_erratic():
    """The check has to be able to say yes as well as no."""
    nights = [
        night(6, hours=7.5, bed=clock(21, 0)),
        night(5, hours=7.5, bed=clock(0, 30)),
        night(4, hours=7.5, bed=clock(2, 15)),
        night(3, hours=7.5, bed=clock(22, 45)),
    ]
    consistency = sleep_metrics(nights, AS_OF).metrics["bedtime_consistency"]
    assert consistency.value is not None
    assert consistency.value > 60, f"got {consistency.value} minutes of spread"


def test_an_identical_bedtime_has_essentially_no_spread():
    nights = [night(n, hours=7.5, bed=clock(23, 0)) for n in (6, 5, 4, 3)]
    consistency = sleep_metrics(nights, AS_OF).metrics["bedtime_consistency"]
    assert consistency.value == pytest.approx(0.0, abs=1e-6)


def test_wake_consistency_is_computed_separately():
    nights = [
        night(6, hours=7.5, bed=clock(23, 0), wake=clock(6, 30)),
        night(5, hours=7.5, bed=clock(1, 0), wake=clock(6, 35)),
        night(4, hours=7.5, bed=clock(22, 0), wake=clock(6, 25)),
    ]
    group = sleep_metrics(nights, AS_OF)
    # An erratic bedtime with a consistent alarm is a real pattern, and the
    # two figures have to be able to disagree.
    assert group.metrics["wake_consistency"].value < 20
    assert group.metrics["bedtime_consistency"].value > 60


def test_clock_consistency_needs_two_nights():
    nights = [night(6, hours=7.5, bed=clock(23, 0))]
    consistency = sleep_metrics(nights, AS_OF).metrics["bedtime_consistency"]
    assert consistency.value is None
    assert consistency.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE


def test_times_spread_round_the_clock_have_no_centre():
    """Four bedtimes six hours apart have no meaningful mean.

    Reporting one would imply a centre that does not exist, which is worse
    than saying nothing.
    """
    nights = [
        night(6, hours=6, bed=clock(0, 0)),
        night(5, hours=6, bed=clock(6, 0)),
        night(4, hours=6, bed=clock(12, 0)),
        night(3, hours=6, bed=clock(18, 0)),
    ]
    consistency = sleep_metrics(nights, AS_OF).metrics["bedtime_consistency"]
    assert consistency.value is None
    assert consistency.unavailable_reason is Unavailable.NOT_APPLICABLE
    assert "no centre" in (consistency.note or "")


def test_the_mean_clock_note_is_readable():
    nights = [night(n, hours=7.5, bed=clock(22, 30)) for n in (6, 5, 4)]
    mean_clock = sleep_metrics(nights, AS_OF).metrics["bedtime_mean_clock"]
    assert "22:30" in (mean_clock.note or "")
    assert "circular" in (mean_clock.note or "")


# ── Window ────────────────────────────────────────────────────────────────

def test_the_as_of_night_is_excluded():
    nights = [
        night(3, hours=7.5), night(2, hours=7.5), night(1, hours=7.5),
        night(0, hours=2.0),   # last night, still being recorded
    ]
    group = sleep_metrics(nights, AS_OF)
    assert group.metrics["duration_mean"].value == pytest.approx(7.5)
    assert group.metrics["nights_observed"].value == 3.0


def test_a_longer_span_can_be_requested():
    nights = [night(n, hours=7.5) for n in range(1, 28)]
    group = sleep_metrics(nights, AS_OF, span=28)
    assert group.metrics["duration_mean"].expected_days == 28
    assert group.metrics["duration_mean"].observed_days == 27


def test_no_nights_at_all_is_no_data():
    group = sleep_metrics([], AS_OF)
    assert group.metrics["duration_mean"].unavailable_reason is Unavailable.NO_DATA
    assert group.metrics["nights_observed"].value == 0.0
    assert group.metrics["bedtime_consistency"].value is None


# ── Subjective scales ─────────────────────────────────────────────────────

def test_a_subjective_mean_states_its_direction():
    """Without it, "soreness improved" and "soreness increased" are the same
    number moving and a reader cannot tell which happened."""
    values = {
        "soreness_level": [
            DailyValue(day=days_before(n), value=v, unit=Unit.SCORE)
            for n, v in ((6, 6), (5, 5), (4, 4))
        ],
        "energy": [
            DailyValue(day=days_before(n), value=v, unit=Unit.SCORE)
            for n, v in ((6, 7), (5, 8), (4, 8))
        ],
    }
    group = subjective_metrics(values, AS_OF)

    soreness = group.metrics["soreness_level_mean"]
    assert soreness.value == pytest.approx(5.0)
    assert "lower is better" in (soreness.note or "")

    energy = group.metrics["energy_mean"]
    assert energy.value == pytest.approx((7 + 8 + 8) / 3)
    assert "higher is better" in (energy.note or "")


def test_a_week_over_week_change_needs_both_windows():
    current = [
        DailyValue(day=days_before(n), value=v, unit=Unit.SCORE)
        for n, v in ((6, 4), (5, 4), (4, 4))
    ]
    previous = [
        DailyValue(day=days_before(n), value=v, unit=Unit.SCORE)
        for n, v in ((13, 7), (12, 7))
    ]
    group = subjective_metrics({"soreness_level": current + previous}, AS_OF)
    change = group.metrics["soreness_level_change"]
    assert change.value == pytest.approx(4.0 - 7.0)
    assert "lower is better" in (change.note or "")


def test_a_missing_previous_window_blocks_the_change():
    current = [
        DailyValue(day=days_before(n), value=5, unit=Unit.SCORE)
        for n in (6, 5, 4)
    ]
    group = subjective_metrics({"fatigue": current}, AS_OF)
    change = group.metrics["fatigue_change"]
    assert change.value is None
    assert change.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert "0" in (change.note or "")
    # The mean is still available: it does not depend on last week.
    assert group.metrics["fatigue_mean"].value == pytest.approx(5.0)


def test_one_reported_day_gives_no_subjective_mean():
    values = {
        "stress": [DailyValue(day=days_before(3), value=8, unit=Unit.SCORE)],
    }
    group = subjective_metrics(values, AS_OF)
    assert group.metrics["stress_mean"].value is None


# ── Determinism ───────────────────────────────────────────────────────────

def test_sleep_metrics_do_not_depend_on_input_order():
    nights = [
        night(6, hours=7.5, bed=clock(23, 50), wake=clock(7, 20)),
        night(5, hours=6.75, bed=clock(0, 10), wake=clock(6, 55)),
        night(4, hours=8.0, bed=clock(23, 30), wake=clock(7, 30)),
        night(3, hours=7.25, bed=clock(0, 5), wake=clock(7, 20)),
    ]
    forward = sleep_metrics(nights, AS_OF, target_hours=8.0)
    backward = sleep_metrics(list(reversed(nights)), AS_OF, target_hours=8.0)
    for key in forward.metrics:
        a, b = forward.metrics[key].value, backward.metrics[key].value
        if a is None or b is None:
            assert a == b, key
        else:
            assert a == pytest.approx(b), key


def test_every_sleep_metric_names_its_formula():
    nights = [night(n, hours=7.5, bed=clock(23, 0)) for n in (6, 5, 4)]
    group = sleep_metrics(nights, AS_OF, target_hours=8.0)
    for key, metric in group.metrics.items():
        assert metric.formula, f"{key} does not name its formula"
        assert metric.analytics_version >= 1
