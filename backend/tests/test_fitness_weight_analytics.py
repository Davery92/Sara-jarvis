"""Step 15 of FITNESS_COACH_IMPLEMENTATION_PLAN: weight analytics, against
hand-derived fixtures.

Every expected value below is computed by hand in the test, not by calling
the function under test. A test that recomputes its subject proves only that
the subject is deterministic.

Pure units, no database. That is part of the contract being asserted: these
numbers must come out the same from a route, a Celery task and a review, and
a function that reached for a connection could not promise that.

The failure modes these pin down all produce a confident wrong number:

* A one-reading-per-week "velocity", which is the difference of two numbers
  and would justify a diet change on the strength of one glass of water.
* A regression over sequence position rather than real day offsets, which
  treats a three-week gap as one day.
* Filling a missing day with zero, which drags a mean down and reads as loss.
* An EWMA substituted for a weekly mean, which lags and understates change.
"""
from datetime import date, timedelta

import pytest

from app.schemas.fitness_coach import Quality, Unavailable, Unit
from app.services.fitness.analytics import (
    MIN_DAYS_FOR_REGRESSION,
    MIN_DAYS_PER_WEEK_WINDOW,
    MIN_SPAN_DAYS_FOR_REGRESSION,
    DailyValue,
    weight_metrics,
    window,
)

AS_OF = date(2026, 10, 1)


def kg(day: date, value: float, **kwargs) -> DailyValue:
    return DailyValue(day=day, value=value, unit=Unit.KG, **kwargs)


def days_before(n: int) -> date:
    return AS_OF - timedelta(days=n)


# ── Windows ───────────────────────────────────────────────────────────────

def test_the_window_is_half_open_and_excludes_the_as_of_day():
    """A completed review passes the athlete's today.

    Including it would average in a day that is not over, and a partial day
    drags every mean toward zero.
    """
    period = window(AS_OF, 7)
    assert period.start == date(2026, 9, 24)
    assert period.end == AS_OF
    assert period.days == 7
    assert period.contains(date(2026, 9, 24))
    assert not period.contains(AS_OF), "the as-of day is excluded"
    assert period.contains(date(2026, 9, 30))


# ── Latest ────────────────────────────────────────────────────────────────

def test_latest_weight_carries_its_measurement_date():
    """"81.2" means nothing without when. A month-old reading read as
    current is how a stale number becomes a decision."""
    values = [kg(days_before(10), 83.0), kg(days_before(2), 81.2)]
    group = weight_metrics(values, AS_OF)
    latest = group.metrics["latest"]
    assert latest.value == 81.2
    assert latest.unit is Unit.KG
    assert days_before(2).isoformat() in (latest.note or "")


def test_no_weight_at_all_is_unavailable_not_zero():
    group = weight_metrics([], AS_OF)
    latest = group.metrics["latest"]
    assert latest.value is None
    assert latest.unavailable_reason is Unavailable.NO_DATA


# ── Means ─────────────────────────────────────────────────────────────────

def test_the_seven_day_mean_is_hand_checkable():
    values = [
        kg(days_before(6), 81.0),
        kg(days_before(5), 81.4),
        kg(days_before(3), 80.8),
        kg(days_before(1), 81.2),
    ]
    expected = (81.0 + 81.4 + 80.8 + 81.2) / 4
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert mean.value == pytest.approx(expected)
    assert mean.observed_days == 4
    assert mean.expected_days == 7, "the calendar span is reported separately"


def test_a_missing_day_is_never_filled_with_zero():
    """The specific arithmetic that would invent weight loss.

    Three days observed out of seven. Dividing by seven would report ~34.8 kg
    for an 81 kg athlete.
    """
    values = [
        kg(days_before(6), 81.0),
        kg(days_before(4), 81.2),
        kg(days_before(2), 81.1),
    ]
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert mean.value == pytest.approx((81.0 + 81.2 + 81.1) / 3)
    assert mean.value != pytest.approx((81.0 + 81.2 + 81.1) / 7)
    assert mean.observed_days == 3 and mean.expected_days == 7


def test_a_sparse_window_is_flagged_sparse():
    values = [kg(days_before(6), 81.0), kg(days_before(2), 81.2),
              kg(days_before(1), 81.1)]
    group = weight_metrics(values, AS_OF)
    assert Quality.SPARSE in group.metrics["mean_7d"].quality_flags


def test_too_few_days_gives_no_mean_rather_than_a_bad_one():
    values = [kg(days_before(3), 81.0), kg(days_before(1), 81.2)]
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert mean.value is None
    assert mean.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert str(MIN_DAYS_PER_WEEK_WINDOW) in (mean.note or "")


def test_the_fourteen_and_twenty_eight_day_means_use_their_own_windows():
    values = [kg(days_before(n), 80.0 + n * 0.1) for n in range(1, 28)]
    group = weight_metrics(values, AS_OF)

    # The windows are [as_of - span, as_of), so days_before(span) is the
    # first day INSIDE them: the 14-day window covers offsets 1..14.
    in_14 = [80.0 + n * 0.1 for n in range(1, 15)]
    in_28 = [80.0 + n * 0.1 for n in range(1, 28)]  # only 27 readings exist
    assert group.metrics["mean_14d"].value == pytest.approx(sum(in_14) / len(in_14))
    assert group.metrics["mean_28d"].value == pytest.approx(sum(in_28) / len(in_28))
    assert group.metrics["mean_14d"].expected_days == 14
    assert group.metrics["mean_28d"].expected_days == 28


# ── Velocity ──────────────────────────────────────────────────────────────

def test_weekly_velocity_is_this_weeks_mean_minus_last_weeks():
    this_week = [81.0, 80.8, 80.6, 80.7]
    last_week = [81.6, 81.5, 81.4]
    values = (
        [kg(days_before(n), v) for n, v in zip((6, 5, 3, 1), this_week)]
        + [kg(days_before(n), v) for n, v in zip((13, 11, 9), last_week)]
    )
    expected = sum(this_week) / len(this_week) - sum(last_week) / len(last_week)

    group = weight_metrics(values, AS_OF)
    velocity = group.metrics["velocity_weekly"]
    assert velocity.value == pytest.approx(expected)
    assert velocity.unit is Unit.KG_PER_WEEK
    assert velocity.value < 0, "this athlete is losing weight"
    assert "4/7" in (velocity.note or "") and "3/7" in (velocity.note or "")


def test_one_reading_per_week_is_not_a_velocity():
    """The specific claim being refused.

    Two numbers a week apart differ by noise — a glass of water, the time of
    day, which scale. Reporting that as a velocity invites changing someone's
    diet on it.
    """
    values = [kg(days_before(1), 80.5), kg(days_before(8), 81.5)]
    group = weight_metrics(values, AS_OF)
    velocity = group.metrics["velocity_weekly"]
    assert velocity.value is None
    assert velocity.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert "not a plateau" in (velocity.note or "")


def test_a_single_reading_cannot_claim_a_plateau():
    """"No measurable change" and "not enough data" are different claims.

    Only the first justifies a change, so one reading must produce the
    second — with every metric absent, not zero.
    """
    group = weight_metrics([kg(days_before(1), 81.0)], AS_OF)
    for key in ("mean_7d", "velocity_weekly", "velocity_percent_weekly",
                "trend_slope_weekly"):
        metric = group.metrics[key]
        assert metric.value is None, f"{key} claimed a value from one reading"
        assert metric.unavailable_reason is not None
    # The reading itself is still reported — it is real.
    assert group.metrics["latest"].value == 81.0


def test_a_missing_previous_week_blocks_the_velocity():
    values = [kg(days_before(n), 81.0) for n in (6, 4, 2)]
    group = weight_metrics(values, AS_OF)
    assert group.metrics["velocity_weekly"].value is None
    # But this week's mean is available: it does not depend on last week.
    assert group.metrics["mean_7d"].value == pytest.approx(81.0)


def test_percent_velocity_divides_by_the_previous_mean():
    this_week = [80.0, 80.0, 80.0]
    last_week = [82.0, 82.0, 82.0]
    values = (
        [kg(days_before(n), v) for n, v in zip((6, 4, 2), this_week)]
        + [kg(days_before(n), v) for n, v in zip((13, 11, 9), last_week)]
    )
    group = weight_metrics(values, AS_OF)
    percent = group.metrics["velocity_percent_weekly"]
    assert percent.value == pytest.approx(100.0 * (80.0 - 82.0) / 82.0)
    assert percent.unit is Unit.PERCENT_PER_WEEK


# ── Regression ────────────────────────────────────────────────────────────

def test_the_slope_uses_real_day_offsets():
    """Sequence position would inflate the slope by the gap ratio.

    A clean 0.1 kg/day loss over 20 days, sampled unevenly. With real
    offsets the slope is 0.7 kg/week; counting positions would make the gaps
    disappear and the slope steeper.
    """
    offsets = [27, 25, 22, 18, 14, 10, 6, 3, 1]
    values = [kg(days_before(n), 80.0 + 0.1 * n) for n in offsets]
    group = weight_metrics(values, AS_OF)
    slope = group.metrics["trend_slope_weekly"]
    # Perfectly linear in days, so the fit is exact: -0.1 kg per day as time
    # moves forward (days_before counts backwards), × 7.
    assert slope.value == pytest.approx(-0.7, abs=1e-9)
    assert slope.unit is Unit.KG_PER_WEEK
    assert slope.observed_days == len(offsets)


def test_a_slope_needs_enough_distinct_days():
    values = [kg(days_before(n), 81.0 - n * 0.05) for n in (20, 15, 10, 5, 1)]
    group = weight_metrics(values, AS_OF)
    slope = group.metrics["trend_slope_weekly"]
    assert slope.value is None
    assert slope.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert str(MIN_DAYS_FOR_REGRESSION) in (slope.note or "")


def test_a_cluster_of_readings_is_not_a_trend():
    """Nine readings inside four days describe four days.

    A count threshold alone would let them claim a 28-day trend, and the
    slope from a tight cluster is arbitrary.
    """
    values = [
        kg(date(2026, 9, 27) + timedelta(days=i % 4), 81.0 + i * 0.1)
        for i in range(9)
    ]
    # Distinct days only, so dedupe by day the way a selection would.
    by_day = {v.day: v for v in values}
    group = weight_metrics(list(by_day.values()) + [
        kg(days_before(1), 80.5), kg(days_before(2), 80.6),
        kg(days_before(3), 80.7), kg(days_before(4), 80.8),
    ], AS_OF)
    slope = group.metrics["trend_slope_weekly"]
    assert slope.value is None
    assert str(MIN_SPAN_DAYS_FOR_REGRESSION) in (slope.note or "")
    assert "cluster of readings" in (slope.note or "")


def test_the_slope_is_order_independent():
    """Same input, different order, same answer.

    A function whose output depends on row order would give the dashboard
    and the review different numbers for one window.
    """
    offsets = [27, 25, 22, 18, 14, 10, 6, 3, 1]
    forward = [kg(days_before(n), 80.0 + 0.1 * n) for n in offsets]
    backward = list(reversed(forward))
    shuffled = [forward[i] for i in (4, 0, 8, 2, 6, 1, 7, 3, 5)]

    a = weight_metrics(forward, AS_OF).metrics["trend_slope_weekly"].value
    b = weight_metrics(backward, AS_OF).metrics["trend_slope_weekly"].value
    c = weight_metrics(shuffled, AS_OF).metrics["trend_slope_weekly"].value
    assert a == pytest.approx(b) == pytest.approx(c)


# ── Outliers ──────────────────────────────────────────────────────────────

def test_an_outlier_is_flagged_and_kept():
    """A 3 kg overnight jump may be a scale error or a real fluid shift.

    Dropping it would hide a genuine change; the flag says "look at this",
    which is what a human can act on.
    """
    values = [
        kg(days_before(6), 81.0), kg(days_before(5), 81.1),
        kg(days_before(4), 81.0), kg(days_before(3), 80.9),
        kg(days_before(2), 95.0),   # the outlier
        kg(days_before(1), 81.0),
    ]
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert Quality.OUTLIER_PRESENT in mean.quality_flags
    # Still included: the mean reflects what was recorded.
    assert mean.value == pytest.approx(
        (81.0 + 81.1 + 81.0 + 80.9 + 95.0 + 81.0) / 6
    )
    assert mean.observed_days == 6


# ── Units ─────────────────────────────────────────────────────────────────

def test_mixed_units_in_one_window_refuse_rather_than_convert():
    """Converting here would hide that the selection let them through."""
    values = [
        kg(days_before(5), 81.0),
        DailyValue(day=days_before(3), value=178.0, unit=Unit.LB),
        kg(days_before(1), 81.2),
    ]
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert mean.value is None
    assert mean.unavailable_reason is Unavailable.NOT_COMPARABLE


def test_an_unknown_unit_is_not_comparable():
    values = [
        DailyValue(day=days_before(n), value=81.0, unit=Unit.UNKNOWN)
        for n in (5, 3, 1)
    ]
    group = weight_metrics(values, AS_OF)
    assert group.metrics["mean_7d"].unavailable_reason is Unavailable.NOT_COMPARABLE


def test_pounds_work_throughout():
    values = [
        DailyValue(day=days_before(n), value=v, unit=Unit.LB)
        for n, v in ((6, 180.0), (5, 179.6), (3, 179.0), (1, 178.8))
    ]
    group = weight_metrics(values, AS_OF)
    mean = group.metrics["mean_7d"]
    assert mean.unit is Unit.LB
    assert mean.value == pytest.approx((180.0 + 179.6 + 179.0 + 178.8) / 4)


# ── Goals ─────────────────────────────────────────────────────────────────

def test_the_goal_rate_is_labelled_as_a_request_not_an_observation():
    group = weight_metrics([], AS_OF, goal_rate_per_week=-0.4,
                           goal_rate_unit=Unit.KG_PER_WEEK)
    goal = group.metrics["goal_rate"]
    assert goal.value == -0.4
    assert "asked for, not an observation" in (goal.note or "")


def test_velocity_is_compared_against_the_goal_when_both_exist():
    this_week = [80.4, 80.3, 80.2]
    last_week = [81.0, 80.9, 80.8]
    values = (
        [kg(days_before(n), v) for n, v in zip((6, 4, 2), this_week)]
        + [kg(days_before(n), v) for n, v in zip((13, 11, 9), last_week)]
    )
    observed = sum(this_week) / 3 - sum(last_week) / 3
    group = weight_metrics(values, AS_OF, goal_rate_per_week=-0.4,
                           goal_rate_unit=Unit.KG_PER_WEEK)
    comparison = group.metrics["velocity_vs_goal"]
    assert comparison.value == pytest.approx(observed - (-0.4))
    assert "measurement noise" in (comparison.note or "")


def test_no_comparison_is_made_when_the_velocity_is_unavailable():
    group = weight_metrics([kg(days_before(1), 81.0)], AS_OF,
                           goal_rate_per_week=-0.4)
    comparison = group.metrics["velocity_vs_goal"]
    assert comparison.value is None
    assert "no comparison is possible" in (comparison.note or "")


def test_a_goal_change_inside_the_window_is_declared_a_limitation():
    """A window spanning a goal change describes two different intents.

    An aggregate over it is not evidence about either, and saying so is the
    difference between a number and a misleading number.
    """
    values = [kg(days_before(n), 81.0 - n * 0.02) for n in range(1, 28)]
    group = weight_metrics(
        values, AS_OF,
        goal_rate_per_week=-0.4, goal_rate_unit=Unit.KG_PER_WEEK,
        goal_changed_on=days_before(10),
    )
    assert any("goal changed" in note for note in group.limitations)
    assert days_before(10).isoformat() in " ".join(group.limitations)


def test_a_goal_change_outside_the_window_is_not_mentioned():
    values = [kg(days_before(n), 81.0) for n in (6, 4, 2)]
    group = weight_metrics(
        values, AS_OF, goal_rate_per_week=-0.4,
        goal_changed_on=days_before(200),
    )
    assert group.limitations == []


# ── Formula provenance ────────────────────────────────────────────────────

def test_every_metric_names_its_formula_and_version():
    """So "why is this number different from last month's review?" is
    answerable without reading the diff."""
    values = [kg(days_before(n), 81.0 - n * 0.02) for n in range(1, 28)]
    group = weight_metrics(values, AS_OF, goal_rate_per_week=-0.4)
    for key, metric in group.metrics.items():
        assert metric.analytics_version >= 1, key
        if key != "goal_rate":
            assert metric.formula, f"{key} does not name its formula"


def test_the_analytics_module_reads_nothing_and_computes_no_ewma():
    """Two claims, checked structurally rather than by eye.

    1. The module is pure. No database, no Redis, no HTTP — which is what
       makes these numbers identical from a route, a Celery task and a
       review. A single query here would quietly break that promise.
    2. No EWMA. `weight_trend.trend_weight` is an explicitly labelled
       display series; an EWMA lags, so substituting one for a weekly mean
       understates a recent change and misstates velocity.
    """
    import ast
    import inspect
    from app.services.fitness import analytics

    tree = ast.parse(inspect.getsource(analytics))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {"sqlalchemy", "redis", "httpx", "requests"}
    assert not any(
        any(name == f or name.startswith(f + ".") for f in forbidden)
        for name in imported
    ), f"the analytics module must stay pure; it imports {sorted(imported)}"
    assert not any(name.startswith("app.db") for name in imported)
    assert not any(name.startswith("app.services.fitness.data_access") for name in imported)

    # No smoothing coefficient and no EWMA accumulation anywhere in the code
    # (the docstring explains why, which is why this checks the AST rather
    # than the text).
    assignments = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "alpha" not in assignments
    assert not any("trend_weight" in n for n in assignments)
