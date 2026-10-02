"""Deterministic fitness analytics.

FITNESS_COACH_IMPLEMENTATION_PLAN Steps 15-16 / §9. Every function here is
**pure**: it takes already-loaded records, an explicit as-of date and an
explicit timezone, and returns `Metric` objects. No database, no Redis, no
model. That is what makes the numbers reproducible and what lets them be
tested against hand-derived fixtures rather than against a reimplementation
of themselves.

The rules that produce most of the code, each of which prevents a specific
confident wrong answer:

* **Never fabricate a missing day.** The denominator is observed days; the
  calendar span is reported separately. Filling a gap with zero drags a mean
  toward zero and reads as a change.
* **Eligibility thresholds, not best effort.** A velocity computed from one
  reading in each 7-day window is not a velocity. Below threshold the metric
  is `null` with `INSUFFICIENT_COVERAGE`, because "no measurable change" and
  "not enough data to say" are different claims and only one of them
  justifies changing a diet.
* **Real day offsets in a regression.** Using sequence position instead of
  date treats a 3-week gap as one day and inflates the slope.
* **Circular time for bedtimes.** 23:50 and 00:10 are 20 minutes apart, not
  23 hours 40.
* **One target per day, resolved as of that day.** Comparing intake against
  today's target is not adherence.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.schemas.fitness_coach import (
    ANALYTICS_VERSION,
    DayType,
    Metric,
    MetricGroup,
    Period,
    Quality,
    ResolvedTargets,
    StateSection,
    Unavailable,
    Unit,
    unavailable,
)

# ── Eligibility thresholds ────────────────────────────────────────────────
#
# Conservative engineering defaults, not scientific prescriptions (§9). They
# are named, exported and versioned so a review can cite which ones it used
# and a later change is a visible decision rather than a silent drift.

#: Observed days needed in EACH 7-day window before a weekly velocity is
#: reported. Below this, two sparse windows produce a difference of noise.
MIN_DAYS_PER_WEEK_WINDOW = 3
#: Distinct days needed for a regression slope.
MIN_DAYS_FOR_REGRESSION = 8
#: Calendar span the regression's days must cover. Eight readings inside four
#: days describes four days, not a trend.
MIN_SPAN_DAYS_FOR_REGRESSION = 14
#: Complete days needed before a nutrition mean is reported.
MIN_COMPLETE_DAYS_FOR_NUTRITION = 3
#: Nights needed before a sleep mean is reported.
MIN_NIGHTS_FOR_SLEEP = 3
#: Outside this many standard deviations a reading is FLAGGED, never dropped.
#: A genuine 3 kg overnight gain is information.
OUTLIER_SIGMA = 3.0

THRESHOLDS: Dict[str, float] = {
    "min_days_per_week_window": MIN_DAYS_PER_WEEK_WINDOW,
    "min_days_for_regression": MIN_DAYS_FOR_REGRESSION,
    "min_span_days_for_regression": MIN_SPAN_DAYS_FOR_REGRESSION,
    "min_complete_days_for_nutrition": MIN_COMPLETE_DAYS_FOR_NUTRITION,
    "min_nights_for_sleep": MIN_NIGHTS_FOR_SLEEP,
    "outlier_sigma": OUTLIER_SIGMA,
}


# ── Inputs ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DailyValue:
    """One selected observation for one athlete-local day.

    Deliberately not a bare `{date: float}`: the unit and the source count
    travel with the value so a mean cannot silently mix kg and lb, and so a
    day built from three readings can be distinguished from one built from
    one.
    """
    day: date
    value: float
    unit: Unit
    source_count: int = 1
    quality_flags: Tuple[Quality, ...] = ()


@dataclass(frozen=True)
class NutritionDay:
    """One day's intake, with per-field knowledge.

    `known_fields` matters because a day can know its calories and not know
    its fat: averaging fat over the calorie denominator understates it, and
    averaging it as zero understates it worse.
    """
    day: date
    calories: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    status: str                      # 'complete' | 'partial' | 'unknown'
    meal_count: int = 0
    known_fields: Mapping[str, int] = field(default_factory=dict)
    has_estimated_items: bool = False

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"


@dataclass(frozen=True)
class SleepNight:
    """One night, keyed by its logical wake date."""
    day: date
    hours: Optional[float]
    bedtime_minutes: Optional[int] = None   # minutes past midnight, 0-1439
    wake_minutes: Optional[int] = None
    quality: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────────────

def window(end: date, days: int) -> Period:
    """The half-open `[end - days, end)` athlete-local window.

    `end` is exclusive throughout, and a completed weekly review passes the
    athlete's today — so the current, incomplete day is never averaged in.
    A partial day drags every mean toward zero.
    """
    return Period(start=end - timedelta(days=days), end=end)


def _in(period: Period, values: Iterable[DailyValue]) -> List[DailyValue]:
    return [v for v in values if period.contains(v.day)]


def _single_unit(values: Sequence[DailyValue]) -> Optional[Unit]:
    """The one unit these values share, or None if they disagree.

    A mean across mixed units is meaningless, and silently converting here
    would hide that the upstream selection let them through.
    """
    units = {v.unit for v in values}
    if len(units) != 1:
        return None
    unit = units.pop()
    return None if unit is Unit.UNKNOWN else unit


def _flag_outliers(values: Sequence[DailyValue]) -> Tuple[Quality, ...]:
    """Whether any value sits far outside the rest. Flags, never drops.

    A 3 kg overnight gain may be a scale error or a genuine fluid shift, and
    discarding it would hide a real change. The flag says "look at this",
    which is what a human can act on.

    Uses the **median absolute deviation**, not the standard deviation,
    because of masking: in a short window the outlier inflates the very
    sigma it is tested against. Six readings around 81 kg plus one of 95
    gives sigma ≈ 5.7, so the 13.7 kg excursion sits inside 3σ and goes
    unflagged — the one case the check exists for. The median and the MAD are
    both unmoved by a single extreme value.

    0.6745 is the constant that puts MAD on the same scale as a standard
    deviation for normally distributed data, so `OUTLIER_SIGMA` keeps meaning
    "sigmas".
    """
    if len(values) < 4:
        return ()
    numbers = [v.value for v in values]
    median = statistics.median(numbers)
    deviations = [abs(n - median) for n in numbers]
    mad = statistics.median(deviations)
    if mad == 0:
        # Every reading identical but for a few: fall back to a plain spread
        # check, since a MAD of zero makes the scaled threshold zero and
        # would flag any variation at all.
        spread = max(numbers) - min(numbers)
        if spread == 0:
            return ()
        return (
            (Quality.OUTLIER_PRESENT,)
            if max(deviations) > spread * 0.9 and len(numbers) >= 5
            else ()
        )
    scaled = mad / 0.6745
    if any(d > OUTLIER_SIGMA * scaled for d in deviations):
        return (Quality.OUTLIER_PRESENT,)
    return ()


def _coverage_flags(observed: int, expected: int) -> Tuple[Quality, ...]:
    if expected and observed < expected / 2:
        return (Quality.SPARSE,)
    return ()


def _mean_metric(
    key: str,
    values: Sequence[DailyValue],
    period: Period,
    *,
    min_days: int,
    formula: str,
) -> Metric:
    """The mean of the observed days, or an honest absence.

    The denominator is `len(values)` — the days actually observed — and
    `expected_days` is the calendar span, reported separately. Dividing by
    the span would treat an unlogged day as a zero.
    """
    expected = period.days
    if not values:
        return unavailable(
            key, Unavailable.NO_DATA, period=period,
            observed_days=0, expected_days=expected, formula=formula,
            note="no observations in this window",
        )
    unit = _single_unit(values)
    if unit is None:
        return unavailable(
            key, Unavailable.NOT_COMPARABLE, period=period,
            observed_days=len(values), expected_days=expected, formula=formula,
            note="the observations in this window are not all in the same unit",
        )
    if len(values) < min_days:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(values), expected_days=expected,
            unit=unit, formula=formula,
            note=(
                f"{len(values)} of {expected} days observed; at least "
                f"{min_days} are needed before a mean says anything"
            ),
        )
    return Metric(
        key=key,
        value=statistics.fmean(v.value for v in values),
        unit=unit,
        period=period,
        observed_days=len(values),
        expected_days=expected,
        source_count=sum(v.source_count for v in values),
        quality_flags=list(_flag_outliers(values) + _coverage_flags(len(values), expected)),
        formula=formula,
    )


# ── Weight ────────────────────────────────────────────────────────────────

def weight_metrics(
    values: Sequence[DailyValue],
    as_of: date,
    *,
    goal_rate_per_week: Optional[float] = None,
    goal_rate_unit: Optional[Unit] = None,
    goal_changed_on: Optional[date] = None,
) -> MetricGroup:
    """Latest weight, window means, weekly velocity and a longer trend.

    `as_of` is exclusive and athlete-local, so a completed review never
    averages in a partial current day.

    What this deliberately does not do:

    * It does not use `weight_trend.trend_weight`. That is an EWMA display
      series; substituting one for a weekly mean misstates velocity, because
      an EWMA lags and a mean does not.
    * It does not report a velocity from sparse windows. One reading in each
      week gives a difference of two numbers, which is noise, and acting on
      it means changing someone's diet because they drank more water once.
    """
    group = MetricGroup(section=StateSection.WEIGHT)

    if values:
        latest = max(values, key=lambda v: v.day)
        group.metrics["latest"] = Metric(
            key="weight.latest",
            value=latest.value,
            unit=latest.unit,
            period=Period(start=latest.day, end=latest.day + timedelta(days=1)),
            observed_days=1,
            expected_days=1,
            source_count=latest.source_count,
            quality_flags=list(latest.quality_flags),
            formula="selected_daily_value",
            note=f"measured {latest.day.isoformat()}",
        )
    else:
        group.metrics["latest"] = unavailable(
            "weight.latest", Unavailable.NO_DATA,
            note="no weight observation recorded",
        )

    current_week = window(as_of, 7)
    previous_week = Period(start=as_of - timedelta(days=14), end=as_of - timedelta(days=7))

    current_values = _in(current_week, values)
    previous_values = _in(previous_week, values)

    group.metrics["mean_7d"] = _mean_metric(
        "weight.mean_7d", current_values, current_week,
        min_days=MIN_DAYS_PER_WEEK_WINDOW, formula="mean_of_selected_daily_values",
    )
    group.metrics["mean_prev_7d"] = _mean_metric(
        "weight.mean_prev_7d", previous_values, previous_week,
        min_days=MIN_DAYS_PER_WEEK_WINDOW, formula="mean_of_selected_daily_values",
    )
    for span in (14, 28):
        period = window(as_of, span)
        group.metrics[f"mean_{span}d"] = _mean_metric(
            f"weight.mean_{span}d", _in(period, values), period,
            min_days=MIN_DAYS_PER_WEEK_WINDOW,
            formula="mean_of_selected_daily_values",
        )

    group.metrics["velocity_weekly"] = _weekly_velocity(
        current_values, previous_values, current_week, previous_week,
    )
    group.metrics["velocity_percent_weekly"] = _weekly_velocity_percent(
        current_values, previous_values, current_week, previous_week,
    )
    group.metrics["trend_slope_weekly"] = _regression_slope(values, window(as_of, 28))

    if goal_rate_per_week is not None:
        group.metrics["goal_rate"] = Metric(
            key="weight.goal_rate",
            value=goal_rate_per_week,
            unit=goal_rate_unit or Unit.KG_PER_WEEK,
            formula="athlete_goal",
            note="the rate the athlete asked for, not an observation",
        )
        group.metrics["velocity_vs_goal"] = _velocity_vs_goal(
            group.metrics["velocity_weekly"], goal_rate_per_week,
            goal_rate_unit or Unit.KG_PER_WEEK,
        )

    if goal_changed_on is not None and window(as_of, 28).contains(goal_changed_on):
        # A window spanning a goal change describes two different intents, so
        # the aggregate over it is not evidence about either.
        group.limitations.append(
            f"The goal changed on {goal_changed_on.isoformat()}, inside this "
            "window. Figures spanning that date mix two different intents."
        )

    return group


def _weekly_velocity(
    current: Sequence[DailyValue],
    previous: Sequence[DailyValue],
    current_period: Period,
    previous_period: Period,
) -> Metric:
    """Current 7-day mean minus the previous 7-day mean.

    Requires `MIN_DAYS_PER_WEEK_WINDOW` observed days in **each** window. One
    reading per week is a difference of two numbers, and reporting it as a
    velocity invites a diet change on the strength of a single glass of
    water.
    """
    key = "weight.velocity_weekly"
    if len(current) < MIN_DAYS_PER_WEEK_WINDOW or len(previous) < MIN_DAYS_PER_WEEK_WINDOW:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE,
            period=current_period,
            observed_days=len(current), expected_days=current_period.days,
            formula="mean_7d_minus_mean_prev_7d",
            note=(
                f"{len(current)} of 7 days this week and {len(previous)} of 7 "
                f"last week; at least {MIN_DAYS_PER_WEEK_WINDOW} in each are "
                "needed. This is not a plateau, it is not enough data."
            ),
        )
    unit = _single_unit(list(current) + list(previous))
    if unit is None:
        return unavailable(
            key, Unavailable.NOT_COMPARABLE, period=current_period,
            formula="mean_7d_minus_mean_prev_7d",
            note="the two windows are not in the same unit",
        )
    delta = statistics.fmean(v.value for v in current) - statistics.fmean(
        v.value for v in previous
    )
    rate_unit = Unit.KG_PER_WEEK if unit is Unit.KG else Unit.COUNT
    return Metric(
        key=key, value=delta,
        unit=rate_unit if unit is Unit.KG else unit,
        period=current_period,
        observed_days=len(current), expected_days=current_period.days,
        source_count=sum(v.source_count for v in current),
        quality_flags=list(_flag_outliers(list(current) + list(previous))),
        formula="mean_7d_minus_mean_prev_7d",
        note=f"{len(current)}/7 days this week, {len(previous)}/7 last week",
    )


def _weekly_velocity_percent(
    current: Sequence[DailyValue],
    previous: Sequence[DailyValue],
    current_period: Period,
    previous_period: Period,
) -> Metric:
    key = "weight.velocity_percent_weekly"
    if len(current) < MIN_DAYS_PER_WEEK_WINDOW or len(previous) < MIN_DAYS_PER_WEEK_WINDOW:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=current_period,
            observed_days=len(current), expected_days=current_period.days,
            formula="velocity_over_prev_mean",
        )
    previous_mean = statistics.fmean(v.value for v in previous)
    if previous_mean == 0:
        return unavailable(
            key, Unavailable.NOT_APPLICABLE, period=current_period,
            formula="velocity_over_prev_mean",
            note="the previous mean is zero, so a percentage is undefined",
        )
    delta = statistics.fmean(v.value for v in current) - previous_mean
    return Metric(
        key=key, value=100.0 * delta / previous_mean,
        unit=Unit.PERCENT_PER_WEEK, period=current_period,
        observed_days=len(current), expected_days=current_period.days,
        formula="velocity_over_prev_mean",
    )


def _regression_slope(values: Sequence[DailyValue], period: Period) -> Metric:
    """Least-squares slope over **real day offsets**, scaled to per week.

    Day offsets, not sequence position: using position treats a three-week
    gap between two readings as one day and inflates the slope by the ratio.

    Also requires a minimum calendar *span*, not only a count — eight
    readings inside four days describe four days, however many there are.
    """
    key = "weight.trend_slope_weekly"
    sample = _in(period, values)
    if len(sample) < MIN_DAYS_FOR_REGRESSION:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(sample), expected_days=period.days,
            formula="ols_on_day_offsets_times_7",
            note=(
                f"{len(sample)} distinct days; at least "
                f"{MIN_DAYS_FOR_REGRESSION} are needed for a slope"
            ),
        )
    days = sorted(v.day for v in sample)
    span = (days[-1] - days[0]).days
    if span < MIN_SPAN_DAYS_FOR_REGRESSION:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(sample), expected_days=period.days,
            formula="ols_on_day_offsets_times_7",
            note=(
                f"the {len(sample)} readings span only {span} days; at least "
                f"{MIN_SPAN_DAYS_FOR_REGRESSION} are needed, because a cluster "
                "of readings describes its own few days and not a trend"
            ),
        )
    unit = _single_unit(sample)
    if unit is None:
        return unavailable(
            key, Unavailable.NOT_COMPARABLE, period=period,
            formula="ols_on_day_offsets_times_7",
            note="the readings are not all in the same unit",
        )

    origin = days[0]
    xs = [float((v.day - origin).days) for v in sample]
    ys = [v.value for v in sample]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            formula="ols_on_day_offsets_times_7",
            note="every reading is on the same day, so there is no slope",
        )
    slope_per_day = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
    ) / denominator

    return Metric(
        key=key, value=slope_per_day * 7,
        unit=Unit.KG_PER_WEEK if unit is Unit.KG else unit,
        period=period,
        observed_days=len(sample), expected_days=period.days,
        source_count=sum(v.source_count for v in sample),
        quality_flags=list(_flag_outliers(sample)),
        formula="ols_on_day_offsets_times_7",
        note=f"{len(sample)} readings spanning {span} days",
    )


def _velocity_vs_goal(
    velocity: Metric, goal_rate: float, goal_unit: Unit,
) -> Metric:
    key = "weight.velocity_vs_goal"
    if velocity.value is None:
        return unavailable(
            key, velocity.unavailable_reason or Unavailable.INSUFFICIENT_COVERAGE,
            period=velocity.period, formula="velocity_minus_goal_rate",
            note="the observed velocity is not available, so no comparison is possible",
        )
    return Metric(
        key=key, value=velocity.value - goal_rate,
        unit=velocity.unit, period=velocity.period,
        observed_days=velocity.observed_days, expected_days=velocity.expected_days,
        quality_flags=list(velocity.quality_flags),
        formula="velocity_minus_goal_rate",
        note=(
            "positive means faster than asked for; a difference this small "
            "may be measurement noise rather than a real deviation"
        ),
    )


# ── Nutrition ─────────────────────────────────────────────────────────────

def nutrition_metrics(
    days: Sequence[NutritionDay],
    as_of: date,
    *,
    targets_by_day: Optional[Mapping[date, ResolvedTargets]] = None,
    span: int = 7,
) -> MetricGroup:
    """Intake means and adherence, over **complete** days only.

    Three separate counts are reported, not one:

    * complete days — days the athlete confirmed were fully logged. The only
      days a calorie mean is built from, because a partially logged day's
      total is a lower bound, and averaging lower bounds reports a deficit
      nobody ran.
    * partial days — logged something, did not confirm.
    * unknown days — said nothing. **Not** zero calories.

    Adherence divides by *eligible* days, which are the complete days that
    also have a resolved target. A day whose target was never recorded
    cannot be adherent or non-adherent to it.
    """
    group = MetricGroup(section=StateSection.NUTRITION)
    period = window(as_of, span)
    in_window = [d for d in days if period.contains(d.day)]

    complete = [d for d in in_window if d.is_complete]
    partial = [d for d in in_window if d.status == "partial"]
    logged_days = {d.day for d in in_window if d.meal_count > 0}
    unknown_count = period.days - len(logged_days)

    group.metrics["complete_days"] = Metric(
        key="nutrition.complete_days", value=float(len(complete)),
        unit=Unit.COUNT, period=period,
        observed_days=len(complete), expected_days=period.days,
        formula="count_of_days_marked_complete",
    )
    group.metrics["partial_days"] = Metric(
        key="nutrition.partial_days", value=float(len(partial)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="count_of_days_with_meals_but_not_confirmed",
    )
    group.metrics["unknown_days"] = Metric(
        key="nutrition.unknown_days", value=float(unknown_count),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="calendar_days_minus_days_with_any_meal",
        note="days with nothing logged — not days of zero intake",
    )

    # Per-field means, each with its own denominator. A day can know its
    # calories and not know its fat.
    for field_name, unit, attribute in (
        ("calories", Unit.KCAL, "calories"),
        ("protein_g", Unit.GRAM, "protein_g"),
        ("carbs_g", Unit.GRAM, "carbs_g"),
        ("fat_g", Unit.GRAM, "fat_g"),
    ):
        known = [
            DailyValue(day=d.day, value=getattr(d, attribute), unit=unit)
            for d in complete
            if getattr(d, attribute) is not None
        ]
        group.metrics[f"{field_name}_mean"] = _mean_metric(
            f"nutrition.{field_name}_mean", known, period,
            min_days=MIN_COMPLETE_DAYS_FOR_NUTRITION,
            formula="mean_over_complete_days_with_this_field",
        )

    if any(d.has_estimated_items for d in in_window):
        group.limitations.append(
            "Some meals in this window have estimated nutrition rather than "
            "matched servings, so the totals carry that uncertainty."
        )

    if targets_by_day:
        group.metrics["calorie_adherence"] = _adherence(
            complete, targets_by_day, period,
            attribute="calories", key="nutrition.calorie_adherence",
            tolerance_attribute="calorie_tolerance_pct",
        )
        group.metrics["protein_adherence"] = _protein_adherence(
            complete, targets_by_day, period,
        )
        group.metrics["calorie_delta_mean"] = _calorie_delta(
            complete, targets_by_day, period,
        )
    else:
        for key in ("calorie_adherence", "protein_adherence", "calorie_delta_mean"):
            group.metrics[key.split(".")[-1]] = unavailable(
                f"nutrition.{key}", Unavailable.NO_TARGET, period=period,
                note="no targets were resolved for this window",
            )

    return group


def _eligible_days(
    complete: Sequence[NutritionDay],
    targets_by_day: Mapping[date, ResolvedTargets],
    attribute: str,
) -> List[Tuple[NutritionDay, ResolvedTargets]]:
    """Complete days that also have a resolved target for this field.

    A day whose target was never recorded cannot be adherent to it, and
    counting it either way would be a fabrication. `history_unknown` days are
    excluded for the same reason: the current value is not asserted to have
    applied then.
    """
    out: List[Tuple[NutritionDay, ResolvedTargets]] = []
    for day in complete:
        target = targets_by_day.get(day.day)
        if target is None or target.history_unknown:
            continue
        if getattr(target.values, attribute, None) is None:
            continue
        if getattr(day, attribute, None) is None:
            continue
        out.append((day, target))
    return out


def _adherence(
    complete: Sequence[NutritionDay],
    targets_by_day: Mapping[date, ResolvedTargets],
    period: Period,
    *,
    attribute: str,
    key: str,
    tolerance_attribute: str,
) -> Metric:
    """Fraction of eligible days within the target's own tolerance.

    The tolerance is read from the target revision, not hard-coded: "within
    10%" is a versioned setting an athlete or a reviewer can inspect and
    change, and a constant here would make it invisible.
    """
    eligible = _eligible_days(complete, targets_by_day, attribute)
    if not eligible:
        return unavailable(
            key, Unavailable.NO_TARGET, period=period,
            observed_days=0, expected_days=period.days,
            formula="days_within_tolerance_over_eligible_days",
            note=(
                "no day in this window is both fully logged and covered by a "
                "recorded target"
            ),
        )
    if len(eligible) < MIN_COMPLETE_DAYS_FOR_NUTRITION:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(eligible), expected_days=period.days,
            formula="days_within_tolerance_over_eligible_days",
            note=(
                f"{len(eligible)} eligible days; at least "
                f"{MIN_COMPLETE_DAYS_FOR_NUTRITION} are needed"
            ),
        )

    within = 0
    for day, target in eligible:
        intake = getattr(day, attribute)
        goal = getattr(target.values, attribute)
        tolerance = getattr(target.values, tolerance_attribute, 10.0)
        if goal == 0:
            within += 1 if intake == 0 else 0
            continue
        if abs(intake - goal) / goal * 100.0 <= tolerance:
            within += 1
    return Metric(
        key=key, value=within / len(eligible),
        # A fraction 0..1, not a percentage: the consumer decides how to show
        # it, and a number already multiplied by 100 invites being multiplied
        # again.
        unit=Unit.COUNT,
        period=period,
        observed_days=len(eligible), expected_days=period.days,
        formula="days_within_tolerance_over_eligible_days",
        note=(
            f"{within} of {len(eligible)} eligible days; "
            f"{period.days} calendar days in the window"
        ),
    )


def _protein_adherence(
    complete: Sequence[NutritionDay],
    targets_by_day: Mapping[date, ResolvedTargets],
    period: Period,
) -> Metric:
    """Fraction of eligible days **meeting or exceeding** the protein target.

    One-sided deliberately, unlike calories. Eating more protein than the
    target is not a failure, and there is no clinical upper requirement this
    system is in a position to assert — inventing one would mark a perfectly
    good day as non-adherent.
    """
    key = "nutrition.protein_adherence"
    eligible = _eligible_days(complete, targets_by_day, "protein_g")
    if not eligible:
        return unavailable(
            key, Unavailable.NO_TARGET, period=period, expected_days=period.days,
            formula="days_at_or_above_target_over_eligible_days",
        )
    if len(eligible) < MIN_COMPLETE_DAYS_FOR_NUTRITION:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(eligible), expected_days=period.days,
            formula="days_at_or_above_target_over_eligible_days",
        )
    met = sum(
        1 for day, target in eligible
        if day.protein_g >= target.values.protein_g
    )
    return Metric(
        key=key, value=met / len(eligible), unit=Unit.COUNT, period=period,
        observed_days=len(eligible), expected_days=period.days,
        formula="days_at_or_above_target_over_eligible_days",
        note=(
            f"{met} of {len(eligible)} eligible days at or above target. "
            "One-sided: exceeding a protein target is not a miss."
        ),
    )


def _calorie_delta(
    complete: Sequence[NutritionDay],
    targets_by_day: Mapping[date, ResolvedTargets],
    period: Period,
) -> Metric:
    """Mean (intake − target) over eligible days, in kcal.

    Each day is compared against **its own** target. Comparing a month of
    intake against today's target is not a deficit, it is an artefact of
    when the target was last edited.
    """
    key = "nutrition.calorie_delta_mean"
    eligible = _eligible_days(complete, targets_by_day, "calories")
    if len(eligible) < MIN_COMPLETE_DAYS_FOR_NUTRITION:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(eligible), expected_days=period.days,
            formula="mean_intake_minus_same_day_target",
        )
    deltas = [
        day.calories - target.values.calories for day, target in eligible
    ]
    distinct_targets = {target.values.calories for _, target in eligible}
    return Metric(
        key=key, value=statistics.fmean(deltas), unit=Unit.KCAL, period=period,
        observed_days=len(eligible), expected_days=period.days,
        formula="mean_intake_minus_same_day_target",
        note=(
            f"each day against its own target"
            + (f" ({len(distinct_targets)} different targets in this window)"
               if len(distinct_targets) > 1 else "")
        ),
    )


# ── Sleep ─────────────────────────────────────────────────────────────────

def sleep_metrics(
    nights: Sequence[SleepNight],
    as_of: date,
    *,
    target_hours: Optional[float] = None,
    span: int = 7,
) -> MetricGroup:
    """Nightly duration, deviation from target, and clock consistency.

    Bedtime and wake consistency use **circular** statistics. 23:50 and
    00:10 are 20 minutes apart; linear arithmetic on minutes-past-midnight
    makes them 23 hours 40 apart and reports an athlete with a very regular
    bedtime as wildly inconsistent.
    """
    group = MetricGroup(section=StateSection.SLEEP)
    period = window(as_of, span)
    in_window = [n for n in nights if period.contains(n.day)]

    durations = [
        DailyValue(day=n.day, value=n.hours, unit=Unit.HOUR)
        for n in in_window if n.hours is not None
    ]
    group.metrics["duration_mean"] = _mean_metric(
        "sleep.duration_mean", durations, period,
        min_days=MIN_NIGHTS_FOR_SLEEP, formula="mean_of_selected_nightly_totals",
    )
    group.metrics["nights_observed"] = Metric(
        key="sleep.nights_observed", value=float(len(durations)),
        unit=Unit.COUNT, period=period,
        observed_days=len(durations), expected_days=period.days,
        formula="count_of_nights_with_a_duration",
    )

    if target_hours is not None and group.metrics["duration_mean"].value is not None:
        group.metrics["deviation_from_target"] = Metric(
            key="sleep.deviation_from_target",
            value=group.metrics["duration_mean"].value - target_hours,
            unit=Unit.HOUR, period=period,
            observed_days=len(durations), expected_days=period.days,
            formula="mean_duration_minus_target",
        )
    else:
        group.metrics["deviation_from_target"] = unavailable(
            "sleep.deviation_from_target",
            Unavailable.NO_TARGET if target_hours is None
            else Unavailable.INSUFFICIENT_COVERAGE,
            period=period,
        )

    if len(durations) >= 2:
        group.metrics["duration_variability"] = Metric(
            key="sleep.duration_variability",
            value=statistics.stdev(v.value for v in durations),
            unit=Unit.HOUR, period=period,
            observed_days=len(durations), expected_days=period.days,
            formula="sample_stdev_of_nightly_totals",
        )
    else:
        group.metrics["duration_variability"] = unavailable(
            "sleep.duration_variability", Unavailable.INSUFFICIENT_COVERAGE,
            period=period, observed_days=len(durations),
            note="two nights are needed for a spread",
        )

    group.metrics["bedtime_consistency"] = _clock_consistency(
        [n.bedtime_minutes for n in in_window if n.bedtime_minutes is not None],
        period, key="sleep.bedtime_consistency",
    )
    group.metrics["wake_consistency"] = _clock_consistency(
        [n.wake_minutes for n in in_window if n.wake_minutes is not None],
        period, key="sleep.wake_consistency",
    )
    group.metrics["bedtime_mean_clock"] = _circular_mean_clock(
        [n.bedtime_minutes for n in in_window if n.bedtime_minutes is not None],
        period, key="sleep.bedtime_mean_clock",
    )

    return group


def _circular_stats(minutes: Sequence[int]) -> Tuple[float, float]:
    """Circular mean (minutes past midnight) and resultant length.

    Each time becomes a unit vector on a 24-hour circle; the mean is the
    angle of their sum. The resultant length is between 0 (times spread all
    round the clock) and 1 (identical times), which is what makes a
    consistency figure meaningful across midnight.
    """
    radians = [2 * math.pi * m / 1440.0 for m in minutes]
    sin_sum = sum(math.sin(r) for r in radians)
    cos_sum = sum(math.cos(r) for r in radians)
    n = len(minutes)
    mean_angle = math.atan2(sin_sum / n, cos_sum / n)
    if mean_angle < 0:
        mean_angle += 2 * math.pi
    resultant = math.hypot(sin_sum / n, cos_sum / n)
    return mean_angle * 1440.0 / (2 * math.pi), resultant


#: Below this resultant length the times are effectively spread round the
#: clock and have no centre. Reporting a mean or a spread for them would
#: imply a middle that does not exist — four bedtimes six hours apart is the
#: canonical case, and floating point means the resultant is a tiny non-zero
#: number rather than exactly zero.
MIN_CIRCULAR_RESULTANT = 0.05


def _circular_mean_clock(
    minutes: Sequence[int], period: Period, *, key: str,
) -> Metric:
    if not minutes:
        return unavailable(
            key, Unavailable.NO_DATA, period=period,
            formula="circular_mean_of_clock_times",
        )
    mean_minutes, resultant = _circular_stats(minutes)
    if resultant < MIN_CIRCULAR_RESULTANT:
        return unavailable(
            key, Unavailable.NOT_APPLICABLE, period=period,
            observed_days=len(minutes), expected_days=period.days,
            formula="circular_mean_of_clock_times",
            note=(
                "the times are spread across the clock with no centre, so a "
                "mean would imply a middle that does not exist"
            ),
        )
    return Metric(
        key=key, value=mean_minutes, unit=Unit.MINUTE, period=period,
        observed_days=len(minutes), expected_days=period.days,
        formula="circular_mean_of_clock_times",
        note=(
            f"{int(mean_minutes) // 60:02d}:{int(mean_minutes) % 60:02d} — "
            "circular, so times either side of midnight average correctly"
        ),
    )


def _clock_consistency(
    minutes: Sequence[int], period: Period, *, key: str,
) -> Metric:
    """Circular spread in minutes. Lower is more consistent.

    Derived from the resultant length rather than from a standard deviation
    of minutes-past-midnight: the latter reports 23:50/00:10 as a ~12-hour
    spread, which is the exact failure this exists to avoid.
    """
    if len(minutes) < 2:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(minutes),
            formula="circular_standard_deviation",
            note="two nights are needed for a spread",
        )
    _, resultant = _circular_stats(minutes)
    if resultant < MIN_CIRCULAR_RESULTANT:
        # Times spread round the clock. A number here would imply a centre
        # that does not exist — and the circular SD formula diverges as the
        # resultant approaches zero, so it would be a large meaningless
        # number rather than an obviously wrong one.
        return unavailable(
            key, Unavailable.NOT_APPLICABLE, period=period,
            observed_days=len(minutes), expected_days=period.days,
            formula="circular_standard_deviation",
            note=(
                "the times are spread across the clock with no centre, so "
                "there is nothing for a spread to be measured around"
            ),
        )
    circular_sd_radians = math.sqrt(-2 * math.log(resultant))
    spread_minutes = circular_sd_radians * 1440.0 / (2 * math.pi)
    return Metric(
        key=key,
        # Capped at six hours. Beyond that the circular SD is dominated by
        # how the formula diverges rather than by the data, and "more than
        # six hours of spread" is the whole of what it can honestly say.
        value=min(spread_minutes, 360.0),
        unit=Unit.MINUTE, period=period,
        observed_days=len(minutes), expected_days=period.days,
        formula="circular_standard_deviation",
        quality_flags=[Quality.SPARSE] if spread_minutes > 360.0 else [],
        note=(
            "minutes of spread; 23:50 and 00:10 are 20 minutes apart here"
            + (". Capped at 360: beyond that the figure says only 'very "
               "irregular'." if spread_minutes > 360.0 else "")
        ),
    )


# ── Subjective scales ─────────────────────────────────────────────────────

def subjective_metrics(
    values_by_field: Mapping[str, Sequence[DailyValue]],
    as_of: date,
    *,
    span: int = 7,
) -> MetricGroup:
    """Means and week-over-week change for the 1-10 check-in scales.

    The direction travels in the note, from `SCALE_DIRECTIONS`. Without it,
    "soreness improved" and "soreness increased" are the same number moving
    and a reader cannot tell which happened.
    """
    from app.schemas.fitness_coach import SCALE_DIRECTIONS

    group = MetricGroup(section=StateSection.RECOVERY)
    current = window(as_of, span)
    previous = Period(
        start=as_of - timedelta(days=span * 2), end=as_of - timedelta(days=span),
    )

    for field_name, values in values_by_field.items():
        direction = SCALE_DIRECTIONS.get(field_name)
        in_current = _in(current, values)
        mean = _mean_metric(
            f"recovery.{field_name}_mean", in_current, current,
            min_days=2, formula="mean_of_reported_days",
        )
        if direction and mean.value is not None:
            mean = mean.model_copy(update={
                "note": f"1-10, {direction.replace('_', ' ')}",
            })
        group.metrics[f"{field_name}_mean"] = mean

        in_previous = _in(previous, values)
        if len(in_current) >= 2 and len(in_previous) >= 2:
            change = statistics.fmean(v.value for v in in_current) - statistics.fmean(
                v.value for v in in_previous
            )
            group.metrics[f"{field_name}_change"] = Metric(
                key=f"recovery.{field_name}_change", value=change,
                unit=Unit.SCORE, period=current,
                observed_days=len(in_current), expected_days=current.days,
                formula="mean_this_window_minus_mean_previous_window",
                note=(
                    f"1-10, {direction.replace('_', ' ')}"
                    if direction else "1-10 scale"
                ),
            )
        else:
            group.metrics[f"{field_name}_change"] = unavailable(
                f"recovery.{field_name}_change", Unavailable.INSUFFICIENT_COVERAGE,
                period=current, observed_days=len(in_current),
                note=(
                    f"{len(in_current)} days this window and {len(in_previous)} "
                    "last; two in each are needed for a change"
                ),
            )

    return group


# ─────────────────────────────────────────────────────────────────────────
# Training (Step 16)
# ─────────────────────────────────────────────────────────────────────────

#: Comparable exposures needed before a strength trend or a stagnation claim.
MIN_EXPOSURES_FOR_TREND = 3
#: Calendar span those exposures must cover.
MIN_SPAN_DAYS_FOR_TREND = 14
#: Rep range Epley is applied over. Outside it the estimate is not reported:
#: at one rep the performed load IS the maximum, and above ten the formula's
#: error grows past the point where the number means anything.
EPLEY_MIN_REPS = 1
EPLEY_MAX_REPS = 10
EPLEY_FORMULA_VERSION = "epley_v1"

THRESHOLDS.update({
    "min_exposures_for_trend": MIN_EXPOSURES_FOR_TREND,
    "min_span_days_for_trend": MIN_SPAN_DAYS_FOR_TREND,
    "epley_max_reps": EPLEY_MAX_REPS,
})


@dataclass(frozen=True)
class SessionRecord:
    """One de-duplicated training bout.

    `was_planned` and `status` are separate because the denominator for
    adherence is the *prescription*, and a session that was never planned
    cannot be a missed one.
    """
    key: str
    day: Optional[date]
    status: str                   # planned|in_progress|completed|skipped|abandoned
    was_planned: bool
    completed_sets: int = 0


@dataclass(frozen=True)
class SetRecord:
    """One performed set, already unit-resolved.

    `load` is the **effective external load** — per-hand already doubled,
    assisted and bodyweight already excluded by the caller. Doing that here
    would need the exercise's convention, and spreading that knowledge is how
    two surfaces come to disagree about what a set lifted.
    """
    set_id: str
    day: date
    exercise_id: Optional[str]
    exercise_name: str
    occurrence_id: Optional[str]
    session_key: Optional[str]
    reps: Optional[int]
    load: Optional[float]
    load_unit: Unit
    set_kind: str                 # working|warmup|drop
    set_role: Optional[str] = None
    counts_toward_target: bool = True
    voided: bool = False
    skipped: bool = False
    effort: Optional[float] = None
    effort_scale: Optional[str] = None   # 'rir' | 'rpe'
    load_comparable: bool = True
    primary_muscles: Tuple[str, ...] = ()
    secondary_muscles: Tuple[str, ...] = ()

    @property
    def is_live(self) -> bool:
        return not self.voided and not self.skipped

    @property
    def is_working(self) -> bool:
        """Working sets only. Roles are roles OF a working set.

        A top set, a backoff and an AMRAP are all `set_kind='working'` with a
        role; treating `set_role` as a kind would make a top set stop
        counting toward the prescribed target.
        """
        return self.set_kind == "working"


def training_metrics(
    sessions: Sequence[SessionRecord],
    sets: Sequence[SetRecord],
    as_of: date,
    *,
    planned_from_snapshot: Optional[int] = None,
    span: int = 7,
) -> MetricGroup:
    """Session counts, working-set volume, muscle exposure and tonnage.

    The adherence denominator comes from `planned_from_snapshot` — the
    prescription as it stood — and is `None` when that history was never
    recorded. Using today's templates instead would mean editing a template
    retroactively changes last week's adherence, which is the same class of
    error the target revisions exist to prevent.
    """
    group = MetricGroup(section=StateSection.TRAINING)
    period = window(as_of, span)

    in_window = [s for s in sessions if s.day and period.contains(s.day)]
    completed = [s for s in in_window if s.status == "completed"]
    skipped = [s for s in in_window if s.status == "skipped"]
    in_progress = [s for s in in_window if s.status == "in_progress"]

    group.metrics["sessions_completed"] = Metric(
        key="training.sessions_completed", value=float(len(completed)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        source_count=len(in_window),
        formula="distinct_deduplicated_sessions_with_status_completed",
        note=(
            "planned and active rows for one bout count once; a two-a-day "
            "counts twice"
        ),
    )
    group.metrics["sessions_skipped"] = Metric(
        key="training.sessions_skipped", value=float(len(skipped)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="distinct_sessions_with_status_skipped",
    )
    group.metrics["sessions_in_progress"] = Metric(
        key="training.sessions_in_progress", value=float(len(in_progress)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="distinct_sessions_still_open",
        note="in progress is not the same as skipped",
    )

    if planned_from_snapshot is None:
        group.metrics["session_adherence"] = unavailable(
            "training.session_adherence", Unavailable.NO_DATA, period=period,
            formula="completed_over_planned_from_snapshot",
            note=(
                "the prescribed session count for this window was never "
                "recorded, so there is no denominator. Using today's "
                "templates would let a template edit change last week's "
                "adherence."
            ),
        )
    elif planned_from_snapshot == 0:
        group.metrics["session_adherence"] = unavailable(
            "training.session_adherence", Unavailable.NOT_APPLICABLE,
            period=period, formula="completed_over_planned_from_snapshot",
            note="nothing was prescribed in this window",
        )
    else:
        group.metrics["session_adherence"] = Metric(
            key="training.session_adherence",
            value=len(completed) / planned_from_snapshot,
            unit=Unit.COUNT, period=period, expected_days=period.days,
            formula="completed_over_planned_from_snapshot",
            note=f"{len(completed)} of {planned_from_snapshot} prescribed",
        )

    live = [s for s in sets if s.is_live and period.contains(s.day)]
    working = [s for s in live if s.is_working]
    warmups = [s for s in live if s.set_kind == "warmup"]
    drops = [s for s in live if s.set_kind == "drop"]

    group.metrics["working_sets"] = Metric(
        key="training.working_sets", value=float(len(working)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="live_sets_with_set_kind_working",
        note=(
            "warm-ups and drop segments excluded; top/backoff/AMRAP are roles "
            "of a working set and are included"
        ),
    )
    group.metrics["warmup_sets"] = Metric(
        key="training.warmup_sets", value=float(len(warmups)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="live_sets_with_set_kind_warmup",
        note="real work, but never counted toward a prescribed target",
    )
    group.metrics["drop_segments"] = Metric(
        key="training.drop_segments", value=float(len(drops)),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="live_sets_with_set_kind_drop",
        note="volume, not completion — each attaches to one parent set",
    )

    group.metrics["tonnage"] = _tonnage(working, period)
    group.metrics.update(_muscle_exposure(working, period))
    return group


def _tonnage(working: Sequence[SetRecord], period: Period) -> Metric:
    """Σ load × reps over sets whose load is actually comparable.

    Excluded, each for a different reason that would otherwise produce a
    meaningless sum:

    * assisted — more assistance is *less* work, so adding it inverts;
    * bodyweight — there is no external load to add;
    * machine stack — the numbers are not kilograms of anything comparable
      to a barbell;
    * unrecorded convention — "40" might be per hand or total.

    And: tonnage is **not** a hypertrophy dose. Two athletes with identical
    tonnage can have done completely different work, which is why the note
    says so rather than leaving the reader to assume.
    """
    eligible = [
        s for s in working
        if s.load is not None and s.reps is not None
        and s.load > 0 and s.reps > 0 and s.load_comparable
    ]
    excluded = len(working) - len(eligible)
    if not eligible:
        return unavailable(
            "training.tonnage", Unavailable.NOT_COMPARABLE, period=period,
            formula="sum_load_times_reps_over_comparable_sets",
            note=(
                f"none of the {len(working)} working sets has a comparable "
                "external load (assisted, bodyweight, machine-stack and "
                "unrecorded conventions are excluded)"
            ),
        )
    unit = {s.load_unit for s in eligible}
    if len(unit) != 1:
        return unavailable(
            "training.tonnage", Unavailable.NOT_COMPARABLE, period=period,
            formula="sum_load_times_reps_over_comparable_sets",
            note="the eligible sets are not all in the same unit",
        )
    total = sum(s.load * s.reps for s in eligible)
    return Metric(
        key="training.tonnage", value=total, unit=unit.pop(), period=period,
        observed_days=len({s.day for s in eligible}), expected_days=period.days,
        source_count=len(eligible),
        formula="sum_load_times_reps_over_comparable_sets",
        quality_flags=[Quality.PARTIAL_DAY] if excluded else [],
        note=(
            f"{len(eligible)} of {len(working)} working sets included"
            + (f"; {excluded} excluded for a non-comparable load convention"
               if excluded else "")
            + ". Not a hypertrophy dose: equal tonnage can be very different work."
        ),
    )


def _muscle_exposure(
    working: Sequence[SetRecord], period: Period,
) -> Dict[str, Metric]:
    """Direct working sets per primary muscle, with secondary kept separate.

    Primary and secondary are never added together. A bench press trains the
    chest directly and the triceps indirectly, and folding them into one
    number both overstates triceps volume and makes the chest figure
    unverifiable. A set with no classified muscle is counted as
    unclassified rather than attributed by guess.
    """
    primary: Dict[str, int] = {}
    secondary: Dict[str, int] = {}
    unclassified = 0
    for record in working:
        if not record.primary_muscles and not record.secondary_muscles:
            unclassified += 1
            continue
        for muscle in record.primary_muscles:
            primary[muscle] = primary.get(muscle, 0) + 1
        for muscle in record.secondary_muscles:
            secondary[muscle] = secondary.get(muscle, 0) + 1

    out: Dict[str, Metric] = {}
    for muscle, count in sorted(primary.items()):
        out[f"direct_sets_{muscle}"] = Metric(
            key=f"training.direct_sets_{muscle}", value=float(count),
            unit=Unit.COUNT, period=period, expected_days=period.days,
            formula="working_sets_with_this_muscle_as_primary",
            note="direct sets only; secondary involvement is reported separately",
        )
    for muscle, count in sorted(secondary.items()):
        out[f"secondary_sets_{muscle}"] = Metric(
            key=f"training.secondary_sets_{muscle}", value=float(count),
            unit=Unit.COUNT, period=period, expected_days=period.days,
            formula="working_sets_with_this_muscle_as_secondary",
            note=(
                "indirect involvement. Never added to the direct count: a "
                "compound trains several muscles and summing them would "
                "overstate every one of them"
            ),
        )
    out["unclassified_sets"] = Metric(
        key="training.unclassified_sets", value=float(unclassified),
        unit=Unit.COUNT, period=period, expected_days=period.days,
        formula="working_sets_with_no_muscle_classification",
        note=(
            "sets whose exercise has no recorded muscles. Reported rather "
            "than assigned — a guess here would invent muscle volume"
        ),
    )
    return out


# ── Estimated 1RM and PRs ─────────────────────────────────────────────────

def epley_1rm(load: float, reps: int) -> Optional[float]:
    """Epley: `load × (1 + reps/30)`, within its stated rep range.

    Returns the performed load unchanged at one rep: that IS the maximum, and
    applying the formula would inflate a true single by 3.3%.

    Returns None outside 1-10 reps. Above ten the formula's error grows past
    the point where the number supports a decision, and reporting it anyway
    would let a set of twenty claim a one-rep max.
    """
    if reps < EPLEY_MIN_REPS or reps > EPLEY_MAX_REPS:
        return None
    if load <= 0:
        return None
    if reps == 1:
        return load
    return load * (1 + reps / 30.0)


def estimated_1rm_metric(
    sets: Sequence[SetRecord], period: Period, *, exercise_name: str,
) -> Metric:
    """Best eligible e1RM in the window, labelled as an estimate.

    Eligibility is narrow on purpose: live working sets, a comparable
    external load, and 1-10 reps. A warm-up, a drop segment, an assisted
    pull-up or a set of twenty cannot support the claim.
    """
    key = "performance.estimated_1rm"
    eligible = [
        s for s in sets
        if s.is_live and s.is_working and s.load_comparable
        and s.load is not None and s.reps is not None
        and epley_1rm(s.load, s.reps) is not None
    ]
    if not eligible:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            formula=EPLEY_FORMULA_VERSION,
            note=(
                "no set in this window is eligible: it needs to be a live "
                f"working set with a comparable load and {EPLEY_MIN_REPS}-"
                f"{EPLEY_MAX_REPS} reps"
            ),
        )
    unit = {s.load_unit for s in eligible}
    if len(unit) != 1:
        return unavailable(
            key, Unavailable.NOT_COMPARABLE, period=period,
            formula=EPLEY_FORMULA_VERSION,
            note="the eligible sets are not all in the same unit",
        )
    best = max(eligible, key=lambda s: epley_1rm(s.load, s.reps) or 0.0)
    value = epley_1rm(best.load, best.reps)
    exact = best.reps == 1
    return Metric(
        key=key, value=value, unit=unit.pop(), period=period,
        observed_days=len({s.day for s in eligible}), expected_days=period.days,
        source_count=len(eligible),
        formula=EPLEY_FORMULA_VERSION,
        note=(
            f"{exercise_name}: {best.load}×{best.reps} on "
            f"{best.day.isoformat()}"
            + (" — an actual single, not an estimate" if exact
               else " — an ESTIMATE from a multi-rep set, not a tested max")
        ),
    )


def strength_trend(
    sets: Sequence[SetRecord], as_of: date, *, exercise_name: str, span: int = 28,
) -> Metric:
    """Change in best e1RM across comparable exposures, or an honest absence.

    "No recorded improvement" over two exposures is **not** a plateau, and
    the distinction decides whether volume gets added. So this requires
    `MIN_EXPOSURES_FOR_TREND` distinct exposures over at least
    `MIN_SPAN_DAYS_FOR_TREND` days, and says which requirement failed.
    """
    key = "performance.strength_trend"
    period = window(as_of, span)
    eligible = [
        s for s in sets
        if period.contains(s.day) and s.is_live and s.is_working
        and s.load_comparable and s.load is not None and s.reps is not None
        and epley_1rm(s.load, s.reps) is not None
    ]
    by_day: Dict[date, float] = {}
    for record in eligible:
        value = epley_1rm(record.load, record.reps)
        if value is None:
            continue
        by_day[record.day] = max(by_day.get(record.day, 0.0), value)

    if len(by_day) < MIN_EXPOSURES_FOR_TREND:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(by_day), expected_days=period.days,
            formula="best_e1rm_last_exposure_minus_first",
            note=(
                f"{exercise_name}: {len(by_day)} comparable exposures in "
                f"{span} days; at least {MIN_EXPOSURES_FOR_TREND} are needed. "
                "This is NOT a plateau — there is not enough to say."
            ),
        )
    days = sorted(by_day)
    covered = (days[-1] - days[0]).days
    if covered < MIN_SPAN_DAYS_FOR_TREND:
        return unavailable(
            key, Unavailable.INSUFFICIENT_COVERAGE, period=period,
            observed_days=len(by_day), expected_days=period.days,
            formula="best_e1rm_last_exposure_minus_first",
            note=(
                f"{exercise_name}: {len(by_day)} exposures spanning only "
                f"{covered} days; at least {MIN_SPAN_DAYS_FOR_TREND} are "
                "needed before a direction means anything"
            ),
        )
    unit = {s.load_unit for s in eligible}
    change = by_day[days[-1]] - by_day[days[0]]
    return Metric(
        key=key, value=change,
        unit=unit.pop() if len(unit) == 1 else Unit.UNKNOWN,
        period=period,
        observed_days=len(by_day), expected_days=period.days,
        source_count=len(eligible),
        formula="best_e1rm_last_exposure_minus_first",
        note=(
            f"{exercise_name}: {len(by_day)} exposures over {covered} days; "
            f"best {by_day[days[0]]:.1f} → {by_day[days[-1]]:.1f}. "
            "Estimates, so a small change may be rep-range noise."
        ),
    )


def exercise_frequency(
    sets: Sequence[SetRecord], as_of: date, *, span: int = 28,
) -> Dict[str, Metric]:
    """Distinct days each exercise was trained.

    Days, not sets: three sets in one session is one exposure, and counting
    sets would make a single session look like a week of work.
    """
    period = window(as_of, span)
    days_by_exercise: Dict[str, set] = {}
    for record in sets:
        if not period.contains(record.day) or not record.is_live:
            continue
        if not record.is_working:
            continue
        key = record.exercise_id or record.exercise_name
        days_by_exercise.setdefault(key, set()).add(record.day)

    return {
        f"frequency_{name}": Metric(
            key=f"training.frequency_{name}", value=float(len(days)),
            unit=Unit.COUNT, period=period, expected_days=period.days,
            formula="distinct_days_with_a_live_working_set",
            note="days, not sets: three sets in one session is one exposure",
        )
        for name, days in sorted(days_by_exercise.items())
    }


# ── Data quality (Step 16) ────────────────────────────────────────────────

def data_quality(
    *,
    weight_group: Optional[MetricGroup] = None,
    nutrition_group: Optional[MetricGroup] = None,
    sleep_group: Optional[MetricGroup] = None,
    training_group: Optional[MetricGroup] = None,
    unresolved_units: int = 0,
    unresolved_exercise_identities: int = 0,
    source_conflicts: int = 0,
    incomplete_workouts: int = 0,
    overdue_cadences: Optional[Sequence[str]] = None,
    stale_profile: bool = False,
    no_effective_target: bool = False,
    insufficient_exposures: Optional[Sequence[str]] = None,
):
    """Coverage as an independent output, not a footnote on another number.

    Separate from model confidence on purpose (§9.6). A review can be very
    confident about a conclusion drawn from two days of data and be wrong
    for exactly that reason; keeping the two apart lets a reader see which
    is which.

    `overdue_cadences` comes from the athlete's own enabled preferences —
    nothing is overdue because this module thinks it should be measured.
    """
    from app.schemas.fitness_coach import DataQuality

    quality = DataQuality(
        unresolved_units=unresolved_units,
        unresolved_exercise_identities=unresolved_exercise_identities,
        source_conflicts=source_conflicts,
        incomplete_workouts=incomplete_workouts,
        overdue_cadences=list(overdue_cadences or []),
        stale_profile=stale_profile,
        no_effective_target=no_effective_target,
        insufficient_comparable_exposures=list(insufficient_exposures or []),
    )

    if weight_group:
        mean = weight_group.metrics.get("mean_7d")
        if mean:
            quality.observed_weight_days = mean.observed_days
            quality.expected_weight_days = mean.expected_days
    if sleep_group:
        nights = sleep_group.metrics.get("nights_observed")
        if nights and nights.value is not None:
            quality.sleep_nights = int(nights.value)
    if nutrition_group:
        for attribute, key in (
            ("nutrition_complete_days", "complete_days"),
            ("nutrition_partial_days", "partial_days"),
            ("nutrition_unknown_days", "unknown_days"),
        ):
            metric = nutrition_group.metrics.get(key)
            if metric and metric.value is not None:
                setattr(quality, attribute, int(metric.value))

    # Every unavailable metric contributes the reason it is unavailable, so
    # "what would help?" is answerable from the state alone rather than
    # needing a human to work it out.
    for group in (weight_group, nutrition_group, sleep_group, training_group):
        if not group:
            continue
        for name, metric in group.metrics.items():
            if metric.value is None and metric.unavailable_reason is not None:
                quality.missing_fields.append(
                    f"{group.section.value}.{name}: {metric.unavailable_reason.value}"
                )
        quality.notes.extend(group.limitations)

    return quality
