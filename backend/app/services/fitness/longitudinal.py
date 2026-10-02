"""Multi-month and multi-year summaries, qualified by what was recorded.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 30.1.

The temptation in a year of training data is to find patterns in it. A
correlation over eighteen months of weight, calories and tonnage will
always produce a number, and the number will be confidently wrong: the
goals changed, the phases changed, the protocol changed, and most of the
days are missing. §30.1 says so directly — "do not fit unexplained
multi-year correlations."

So this module does three things and refuses the fourth:

1. **Splits history into comparable periods.** A period is a stretch with
   one goal and one phase type. A goal change ends a period, because two
   stretches with different goals are two different experiments.
2. **Summarises each period with the same analytics as everything else**,
   through `Metric`, so "no data" stays distinguishable from zero — over a
   year most of these are partly missing.
3. **Compares only pairs that share a goal and have enough coverage**, and
   names every pair it did NOT compare. That list is the honest bulk of
   the output.
4. **Does not correlate anything.** There is no function here that takes
   two series and returns an r value, deliberately.

Every query is bounded and indexed: a year of `workout_log` is tens of
thousands of rows, and an unbounded scan here is a slow page rather than a
wrong answer — but a slow page on the one screen somebody opens to look
back at a year is still a feature nobody uses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import (
    ANALYTICS_VERSION,
    LONGITUDINAL_SUMMARY_VERSION,
    LongitudinalComparison,
    LongitudinalPeriod,
    Metric,
    PeriodCoverage,
    Quality,
    Unavailable,
    Unit,
)
from app.services.fitness.data_access import (
    FitnessDataError, _require_user, athlete_zone,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: The longest span this will summarise in one call. Three years is more
#: history than this system has, and the bound is what keeps a malformed
#: date range from scanning everything.
MAX_SPAN_DAYS = 1100
#: A period shorter than this is not a period: a two-week stretch between
#: goal changes cannot support a weekly rate.
MIN_PERIOD_DAYS = 21
#: Coverage below which a period is summarised but not compared. A claim
#: from 30% coverage is a claim about the 30%, and comparing two of those
#: is a claim about neither.
MIN_COMPARE_COVERAGE = 0.5
#: And the number of observed days a rate needs at all.
MIN_RATE_OBSERVATIONS = 8


@dataclass
class PeriodBounds:
    """One comparable stretch, before any numbers are attached."""
    label: str
    start: date
    #: Exclusive, like every other window in this subsystem.
    end: date
    goal_kind: Optional[str]
    phase_names: List[str]

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def weeks(self) -> float:
        return round(self.days / 7.0, 1)


def comparable_periods(
    db: Session, user_id: str, start: date, end: date,
) -> List[PeriodBounds]:
    """Split [start, end) where the goal changed.

    The goal is the boundary rather than the phase: a program can run three
    phases toward one goal, and splitting on phase would produce periods
    too short to say anything about. A goal change is a change of
    experiment.
    """
    owner = _require_user(user_id)
    if end <= start:
        raise FitnessDataError("end must be after start")
    if (end - start).days > MAX_SPAN_DAYS:
        raise FitnessDataError(
            f"{(end - start).days} days is past the {MAX_SPAN_DAYS}-day "
            f"bound on one summary"
        )

    goals = db.execute(text("""
        SELECT kind, valid_from, valid_until
        FROM fitness_athlete_goal
        WHERE user_id = :u
          AND valid_from < :end
          AND (valid_until IS NULL OR valid_until > :start)
        ORDER BY valid_from ASC, recorded_at ASC
    """), {"u": owner, "start": start, "end": end}).fetchall()

    # Boundaries: the window edges plus every goal transition inside it.
    edges = {start, end}
    for row in goals:
        for moment in (row.valid_from, row.valid_until):
            if moment and start < moment < end:
                edges.add(moment)
    ordered = sorted(edges)

    phases = db.execute(text("""
        SELECT name, start_date, end_date FROM fitness_phase
        WHERE user_id = :u AND start_date IS NOT NULL
          AND start_date < :end
          AND (end_date IS NULL OR end_date >= :start)
        ORDER BY start_date ASC
    """), {"u": owner, "start": start, "end": end}).fetchall()

    periods: List[PeriodBounds] = []
    for left, right in zip(ordered, ordered[1:]):
        if (right - left).days < MIN_PERIOD_DAYS:
            # Too short to support a weekly rate. Skipped rather than
            # merged: merging would put two goals in one period, which is
            # the thing this split exists to prevent.
            continue
        goal = next(
            (
                row.kind for row in goals
                if row.valid_from <= left
                and (row.valid_until is None or row.valid_until > left)
            ),
            None,
        )
        covering = [
            row.name for row in phases
            # `fitness_phase.end_date` is INCLUSIVE, and this window is
            # half-open — hence `>= left` rather than `> left`.
            if row.start_date < right
            and (row.end_date is None or row.end_date >= left)
        ]
        periods.append(PeriodBounds(
            label=(
                f"{left:%b %Y} – {right - timedelta(days=1):%b %Y}"
                + (f" ({goal})" if goal else "")
            ),
            start=left, end=right, goal_kind=goal,
            phase_names=covering[:6],
        ))
    return periods


def summarise_period(
    db: Session, user_id: str, bounds: PeriodBounds,
) -> LongitudinalPeriod:
    """The numbers for one period, each with its own coverage.

    Every figure is a `Metric` carrying the days it was observed over and
    the days expected. Over a year that distinction is the whole value: a
    weekly rate from 40 weigh-ins and one from 6 are different claims, and
    a bare float cannot tell them apart.
    """
    owner = _require_user(user_id)
    tz = athlete_zone(db.execute(text("""
        SELECT timezone FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": owner}).scalar())
    expected = max(bounds.days, 1)
    notes: List[str] = []

    weights = db.execute(text("""
        SELECT DATE(recorded_at) AS day, AVG(value) AS value,
               MIN(unit) AS unit
        FROM health_metric
        WHERE user_id = :u AND metric_type = 'weight'
          AND recorded_at >= :start AND recorded_at < :end
        GROUP BY DATE(recorded_at)
        ORDER BY day ASC
    """), {"u": owner, "start": bounds.start, "end": bounds.end}).fetchall()

    weight_change = weight_rate = None
    if len(weights) >= 2:
        first, last = weights[0], weights[-1]
        span_days = (last.day - first.day).days
        unit = Unit(first.unit) if first.unit else Unit.LB
        delta = float(last.value) - float(first.value)
        weight_change = Metric(
            key="longitudinal.weight_change",
            value=round(delta, 2), unit=unit,
            observed_days=len(weights), expected_days=expected,
            formula="last_minus_first_daily_mean_v1",
        )
        if span_days >= 14 and len(weights) >= MIN_RATE_OBSERVATIONS:
            weight_rate = Metric(
                key="longitudinal.weight_rate_weekly",
                value=round(delta / (span_days / 7.0), 3), unit=unit,
                observed_days=len(weights), expected_days=expected,
                formula="delta_over_span_weeks_v1",
            )
        else:
            weight_rate = Metric(
                key="longitudinal.weight_rate_weekly",
                value=None, unit=unit,
                unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
                observed_days=len(weights), expected_days=expected,
                formula="delta_over_span_weeks_v1",
            )
            notes.append(
                f"No weekly rate for {bounds.label}: "
                f"{len(weights)} weigh-in day(s) over {span_days} days, "
                f"below the {MIN_RATE_OBSERVATIONS} needed."
            )
    else:
        weight_change = Metric(
            key="longitudinal.weight_change",
            value=None, unit=Unit.LB,
            unavailable_reason=Unavailable.NO_DATA,
            observed_days=len(weights), expected_days=expected,
            formula="last_minus_first_daily_mean_v1",
        )

    training = db.execute(text("""
        SELECT COUNT(DISTINCT session_date) AS sessions,
               COUNT(*) AS sets
        FROM workout_log
        WHERE user_id = :u
          AND COALESCE(skipped, FALSE) = FALSE
          AND session_date >= :start AND session_date < :end
    """), {"u": owner, "start": bounds.start, "end": bounds.end}).fetchone()

    sessions_weekly = Metric(
        key="longitudinal.sessions_weekly",
        value=(
            round(training.sessions / (bounds.days / 7.0), 2)
            if training and training.sessions else None
        ),
        unit=Unit.COUNT,
        unavailable_reason=(
            None if training and training.sessions else Unavailable.NO_DATA
        ),
        observed_days=training.sessions if training else 0,
        expected_days=expected,
        formula="sessions_over_span_weeks_v1",
    )

    # Tonnage from comparable loads only, through the shared window
    # consumer, so this figure and the weekly one on the coach overview
    # cannot disagree.
    tonnage_weekly = None
    try:
        from app.services.fitness.consumers import training_window

        window = training_window(db, owner, bounds.start, bounds.end)
        if window["tonnage"]:
            tonnage_weekly = Metric(
                key="longitudinal.tonnage_weekly",
                value=round(window["tonnage"] / (bounds.days / 7.0), 1),
                unit=Unit(window["tonnage_unit"])
                if window.get("tonnage_unit") else Unit.LB,
                observed_days=window["sessions"], expected_days=expected,
                # `quality_flags` is a closed `Quality` enum, not free
                # text: a tonnage with excluded sets is PARTIAL, and the
                # count of what was excluded goes in `note` where a reader
                # can see it.
                quality_flags=(
                    [Quality.PARTIAL]
                    if window.get("sets_excluded_from_tonnage") else []
                ),
                note=(
                    f"{window['sets_excluded_from_tonnage']} set(s) have no "
                    f"comparable load, so this is a floor"
                    if window.get("sets_excluded_from_tonnage") else None
                ),
                formula="tonnage_over_span_weeks_v1",
            )
            if window.get("sets_excluded_from_tonnage"):
                notes.append(
                    f"{window['sets_excluded_from_tonnage']} set(s) in "
                    f"{bounds.label} have no comparable load, so the tonnage "
                    f"is a floor rather than a total."
                )
    except Exception as exc:
        logger.info("[longitudinal] tonnage unavailable: %s", exc)

    nutrition = db.execute(text("""
        SELECT COUNT(DISTINCT DATE(logged_at)) AS days,
               AVG(day_calories) AS calories, AVG(day_protein) AS protein
        FROM (
            SELECT DATE(logged_at) AS logged_at,
                   SUM(calories) AS day_calories,
                   SUM(protein) AS day_protein
            FROM food_log
            WHERE user_id = :u
              AND logged_at >= :start AND logged_at < :end
            GROUP BY DATE(logged_at)
        ) AS per_day
    """), {"u": owner, "start": bounds.start, "end": bounds.end}).fetchone()

    calorie_mean = Metric(
        key="longitudinal.calorie_mean",
        value=(
            round(float(nutrition.calories), 0)
            if nutrition and nutrition.calories is not None else None
        ),
        unit=Unit.KCAL,
        unavailable_reason=(
            None if nutrition and nutrition.calories is not None
            else Unavailable.NO_DATA
        ),
        observed_days=nutrition.days if nutrition else 0,
        expected_days=expected, formula="mean_logged_day_calories_v1",
    )
    protein_mean = Metric(
        key="longitudinal.protein_mean",
        value=(
            round(float(nutrition.protein), 1)
            if nutrition and nutrition.protein is not None else None
        ),
        unit=Unit.GRAM,
        unavailable_reason=(
            None if nutrition and nutrition.protein is not None
            else Unavailable.NO_DATA
        ),
        observed_days=nutrition.days if nutrition else 0,
        expected_days=expected, formula="mean_logged_day_protein_v1",
    )

    sleep = db.execute(text("""
        SELECT COUNT(*) AS nights, AVG(sleep_hours) AS hours
        FROM daily_recovery_log
        WHERE user_id = :u AND sleep_hours IS NOT NULL
          AND log_date >= :start AND log_date < :end
    """), {"u": owner, "start": bounds.start, "end": bounds.end}).fetchone()
    sleep_mean = Metric(
        key="longitudinal.sleep_mean",
        value=(
            round(float(sleep.hours), 2)
            if sleep and sleep.hours is not None else None
        ),
        unit=Unit.HOUR,
        unavailable_reason=(
            None if sleep and sleep.hours is not None else Unavailable.NO_DATA
        ),
        observed_days=sleep.nights if sleep else 0,
        expected_days=expected, formula="mean_recorded_sleep_hours_v1",
    )

    # Period coverage is the WEAKEST of the streams, not their average: a
    # period with 90% weigh-ins and 10% food logs cannot support a
    # nutrition comparison, and an average would report 50% and hide which
    # half is missing.
    ratios = [
        (metric.observed_days or 0) / expected
        for metric in (weight_change, calorie_mean, sleep_mean)
        if metric is not None
    ]
    coverage_ratio = round(min(ratios), 3) if ratios else 0.0
    coverage = (
        PeriodCoverage.GOOD if coverage_ratio >= 0.8
        else PeriodCoverage.PARTIAL if coverage_ratio >= 0.4
        else PeriodCoverage.SPARSE
    )

    return LongitudinalPeriod(
        label=bounds.label, start=bounds.start,
        end=bounds.end - timedelta(days=1), goal_kind=bounds.goal_kind,
        phase_names=bounds.phase_names, weeks=bounds.weeks,
        weight_change=weight_change, weight_rate_weekly=weight_rate,
        tonnage_weekly=tonnage_weekly, sessions_weekly=sessions_weekly,
        calorie_mean=calorie_mean, protein_mean=protein_mean,
        sleep_mean=sleep_mean, coverage=coverage,
        coverage_ratio=coverage_ratio, notes=notes,
    )


def compare(
    db: Session, user_id: str, start: date, end: date,
) -> LongitudinalComparison:
    """Summarise the span and compare only what can honestly be compared.

    §30.1. The `not_compared` list is not an apology — it is the result.
    "These two blocks cannot be compared because one of them has eleven
    food logs" is a more useful answer than a number computed anyway.
    """
    owner = _require_user(user_id)
    bounds = comparable_periods(db, owner, start, end)
    periods = [summarise_period(db, owner, one) for one in bounds]

    comparisons: List[Dict[str, Any]] = []
    not_compared: List[str] = []
    quality_notes: List[str] = []

    for period in periods:
        quality_notes.extend(period.notes)

    for left, right in zip(periods, periods[1:]):
        if left.goal_kind != right.goal_kind:
            not_compared.append(
                f"{left.label} and {right.label}: different goals "
                f"({left.goal_kind or 'unrecorded'} vs "
                f"{right.goal_kind or 'unrecorded'}). Two goals is two "
                f"experiments, and the difference between them is not a "
                f"result."
            )
            continue
        if (left.coverage_ratio or 0) < MIN_COMPARE_COVERAGE:
            not_compared.append(
                f"{left.label}: {(left.coverage_ratio or 0) * 100:.0f}% "
                f"coverage, below the "
                f"{MIN_COMPARE_COVERAGE * 100:.0f}% needed to compare. A "
                f"claim from this much is a claim about that much."
            )
            continue
        if (right.coverage_ratio or 0) < MIN_COMPARE_COVERAGE:
            not_compared.append(
                f"{right.label}: "
                f"{(right.coverage_ratio or 0) * 100:.0f}% coverage, below "
                f"the {MIN_COMPARE_COVERAGE * 100:.0f}% needed to compare."
            )
            continue

        deltas: Dict[str, Any] = {}
        for field_name in ("weight_rate_weekly", "tonnage_weekly",
                           "sessions_weekly", "calorie_mean", "protein_mean",
                           "sleep_mean"):
            before = getattr(left, field_name)
            after = getattr(right, field_name)
            if (before is None or after is None
                    or before.value is None or after.value is None):
                # Named, not dropped: a missing half is why a comparison is
                # absent, and silence would read as "no difference".
                deltas[field_name] = {
                    "delta": None,
                    "unavailable": "one or both periods have no value",
                }
                continue
            if before.unit != after.unit:
                deltas[field_name] = {
                    "delta": None,
                    "unavailable": (
                        f"units differ ({before.unit.value} vs "
                        f"{after.unit.value})"
                    ),
                }
                continue
            deltas[field_name] = {
                "delta": round(after.value - before.value, 3),
                "unit": after.unit.value,
                "before": before.value, "after": after.value,
            }

        comparisons.append({
            "from": left.label, "to": right.label,
            "goal_kind": left.goal_kind,
            "weeks": [left.weeks, right.weeks],
            "coverage": [left.coverage_ratio, right.coverage_ratio],
            "deltas": deltas,
            # Stated on every comparison, because the number above it
            # invites exactly this mistake.
            "caveat": (
                "A difference between two periods is not a cause. The "
                "programme, the sleep, the stress and the season all moved "
                "too."
            ),
        })

    if not periods:
        quality_notes.append(
            f"No period between {start} and {end} is at least "
            f"{MIN_PERIOD_DAYS} days with one goal in force, so there is "
            f"nothing to summarise."
        )

    return LongitudinalComparison(
        summary_version=LONGITUDINAL_SUMMARY_VERSION,
        analytics_version=ANALYTICS_VERSION,
        periods=periods, comparisons=comparisons,
        not_compared=not_compared, data_quality_notes=quality_notes,
    )
