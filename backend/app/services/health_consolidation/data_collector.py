"""Pull a week of health data and pre-compute deterministic stats.

Stats are computed in Python so the LLM only narrates and finds patterns —
never does arithmetic. All numbers in user-facing units (lbs, hours, kcal).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, time
from statistics import mean, stdev
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

import logging

logger = logging.getLogger(__name__)


def previous_iso_week(today: date) -> tuple[date, date]:
    """Return (Mon, Sun) of the most recently completed ISO week relative to `today`.

    Run-time semantics: this is scheduled MONDAY 6 AM ET (cron `0 6 * * 1`), so
    today.weekday()==0 and we return the Mon..Sun that ended yesterday — the week
    that just finished, with fully complete data. NOTE: do NOT move this back to a
    Sunday run — on a Sunday this returns the week-before-last (Sunday-just-past is
    still mid-week), which is exactly the "two weeks ago" bug we fixed 2026-06-28.
    """
    days_since_monday = today.weekday()  # Mon=0..Sun=6
    week_end = today - timedelta(days=days_since_monday + 1)  # last Sunday
    week_start = week_end - timedelta(days=6)                 # the Monday before it
    return week_start, week_end


@dataclass
class RecoveryStats:
    days_logged: int = 0
    hrv_avg: Optional[float] = None
    hrv_min: Optional[int] = None
    hrv_max: Optional[int] = None
    hrv_stdev: Optional[float] = None
    hrv_low_days: List[Dict[str, Any]] = field(default_factory=list)  # bottom-quartile flags
    rhr_avg: Optional[float] = None
    rhr_min: Optional[int] = None
    rhr_max: Optional[int] = None
    sleep_avg_hours: Optional[float] = None
    sleep_min_hours: Optional[float] = None
    sleep_under_6h_count: int = 0
    weight_lbs_start: Optional[float] = None
    weight_lbs_end: Optional[float] = None
    weight_delta_lbs: Optional[float] = None
    # Coverage for that delta. A change between two readings five days apart
    # is a different claim from one across a full week, and without these the
    # report stated both identically.
    weight_days_observed: int = 0
    weight_days_expected: int = 0
    weight_delta_span_days: Optional[int] = None
    daily_rows: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ActivityStats:
    workouts_count: int = 0
    workout_days: int = 0
    workout_dates: List[str] = field(default_factory=list)
    total_sets: int = 0
    total_reps: int = 0
    avg_rpe: Optional[float] = None
    high_rpe_days: List[str] = field(default_factory=list)  # RPE 9+
    food_logs_count: int = 0
    food_days: int = 0
    avg_calories: Optional[float] = None
    avg_protein: Optional[float] = None
    avg_carbs: Optional[float] = None
    avg_fats: Optional[float] = None
    daily_calories: Dict[str, float] = field(default_factory=dict)
    workouts_by_date: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    food_by_date: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Volume from effective loads, with what could not be counted named.
    total_volume_lbs: Optional[float] = None
    sets_excluded_from_volume: Dict[str, int] = field(default_factory=dict)
    # Complete and partial logging days are separate counts: a week with one
    # confirmed day and a week with seven are not the same week.
    food_complete_days: int = 0
    food_partial_days: int = 0
    macro_average_unavailable: Optional[str] = None


@dataclass
class WeeklyDataset:
    user_id: str
    week_start: date
    week_end: date
    recovery: RecoveryStats
    activity: ActivityStats
    fitness_daily: List[Dict[str, Any]]  # aggregated daily totals from fitness_daily_log

    def to_json(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "recovery": asdict(self.recovery),
            "activity": asdict(self.activity),
            "fitness_daily": self.fitness_daily,
        }


def _as_lbs(value: Any, unit: Optional[str]) -> Optional[float]:
    """A logged body weight in pounds, whatever unit it was entered in.

    Refuses to guess when the unit is something neither recognised nor
    blank: "a weight around 180 is probably pounds" is exactly the inference
    that must not be made here, because 180 kg is a real bodyweight.
    """
    if value is None:
        return None
    label = (unit or "lbs").strip().lower()
    if label in ("lb", "lbs", "pound", "pounds", ""):
        return float(value)
    if label in ("kg", "kgs", "kilogram", "kilograms"):
        from app.schemas.fitness_coach import Unit, convert
        return round(convert(float(value), Unit.KG, Unit.LB), 2)
    logger.warning("unrecognised weight unit %r — reading dropped", unit)
    return None


def _safe_avg(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 2) if xs else None


def _safe_stdev(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(stdev(xs), 2) if len(xs) >= 2 else None


def collect_recovery(db: Session, user_id: str, ws: date, we: date) -> RecoveryStats:
    rows = db.execute(
        text("""
            SELECT log_date, hrv, heart_rate, sleep_hours, body_weight, weight_unit
            FROM daily_recovery_log
            WHERE user_id = :uid AND log_date BETWEEN :ws AND :we
            ORDER BY log_date ASC
        """),
        {"uid": user_id, "ws": ws, "we": we},
    ).all()

    s = RecoveryStats()
    # NOT an early return. Body weight comes from the canonical observation
    # stream below, and an athlete can be weighing himself without filling in
    # a check-in row — returning here reported no weight data for him.
    daily = []
    hrvs, rhrs, sleeps, weights = [], [], [], []
    for r in rows:
        rec = {
            "date": r.log_date.isoformat(),
            "hrv": r.hrv,
            "rhr": r.heart_rate,
            "sleep_hours": float(r.sleep_hours) if r.sleep_hours is not None else None,
            # Converted, not discarded. This used to read
            # `(r.weight_unit or "lbs") == "lbs"` and drop anything else, so a
            # week logged in kg reported no weight data at all — and the
            # consolidation prompt was told David had not weighed himself.
            "body_weight_lbs": _as_lbs(r.body_weight, r.weight_unit),
        }
        daily.append(rec)
        if r.hrv is not None:
            hrvs.append(r.hrv)
        if r.heart_rate is not None:
            rhrs.append(r.heart_rate)
        if r.sleep_hours is not None:
            sleeps.append(float(r.sleep_hours))
        if rec["body_weight_lbs"] is not None:
            weights.append(rec["body_weight_lbs"])

    s.days_logged = len(rows)
    s.daily_rows = daily

    if hrvs:
        s.hrv_avg = round(mean(hrvs), 1)
        s.hrv_min = min(hrvs)
        s.hrv_max = max(hrvs)
        s.hrv_stdev = _safe_stdev([float(x) for x in hrvs])
        # flag low-HRV days (≥10 below the week's mean — heuristic for stress/illness)
        threshold = s.hrv_avg - 10
        s.hrv_low_days = [
            {"date": d["date"], "hrv": d["hrv"]}
            for d in daily
            if d["hrv"] is not None and d["hrv"] < threshold
        ]
    if rhrs:
        s.rhr_avg = round(mean(rhrs), 1)
        s.rhr_min = min(rhrs)
        s.rhr_max = max(rhrs)
    if sleeps:
        s.sleep_avg_hours = round(mean(sleeps), 2)
        s.sleep_min_hours = round(min(sleeps), 2)
        s.sleep_under_6h_count = sum(1 for x in sleeps if x < 6.0)
    # Body weight comes from the canonical observation stream, not from this
    # projection column, so this cannot disagree with the Coach API about what
    # David weighed. The projection is still read above for `daily_rows`,
    # which is the per-day table the report renders.
    try:
        from app.services.fitness.consumers import weight_window
        canonical = weight_window(db, user_id, ws, we + timedelta(days=1))
        s.weight_days_observed = canonical["observed_days"]
        s.weight_days_expected = canonical["expected_days"]
        s.weight_lbs_start = canonical["start_lbs"]
        s.weight_lbs_end = canonical["end_lbs"]
        s.weight_delta_lbs = canonical["delta_lbs"]
        s.weight_delta_span_days = canonical["delta_span_days"]
    except Exception as exc:
        logger.warning(
            "weekly weight from canonical observations unavailable (%s): %s",
            type(exc).__name__, exc,
        )
        if weights:
            s.weight_lbs_start = weights[0]
            s.weight_lbs_end = weights[-1]
            s.weight_delta_lbs = round(weights[-1] - weights[0], 2)
            s.weight_days_observed = len(weights)
            s.weight_days_expected = (we - ws).days + 1

    return s


def collect_activity(db: Session, user_id: str, ws: date, we: date) -> ActivityStats:
    """Training and intake for the completed week `[ws, we]` (we is inclusive).

    Step 18 moved the arithmetic to `services/fitness/consumers`, which is
    where the Coach API and `FitnessStateV1` get the same figures. Three
    things this fixes:

    * `workouts_count` was `len(set_rows)` — the field named "workouts" held
      the number of SETS, so one session of 24 sets told the consolidation
      prompt David trained 24 times.
    * volume was absent here but computed as `SUM(weight * reps)` in the two
      sibling readers, over the legacy integer column. Now it is the
      effective load, with the excluded sets named so the figure reads as a
      floor rather than a total.
    * macro averages counted every day with any row, so a logged breakfast
      counted as a day's eating and a cut looked like a crash diet. They now
      average over days the athlete confirmed were fully logged, and the
      partial days are reported separately rather than folded in.
    """
    s = ActivityStats()
    end_exclusive = we + timedelta(days=1)

    from app.services.fitness.consumers import food_days_payload, training_window

    window = training_window(db, user_id, ws, end_exclusive)
    by_date = window["by_date"]

    s.total_sets = window["sets"]
    s.total_reps = window["total_reps"]
    s.workouts_count = window["sessions"]
    s.workout_dates = window["session_dates"] or sorted(by_date.keys())
    s.workout_days = len(s.workout_dates)
    s.workouts_by_date = by_date
    s.avg_rpe = window["avg_rpe"]
    s.total_volume_lbs = window["tonnage"]
    s.sets_excluded_from_volume = window["sets_excluded_from_tonnage"]

    # Flag any day where the hardest set was RPE 9+.
    for d, sets in by_date.items():
        day_rpes = [x["rpe"] for x in sets if x.get("rpe") is not None]
        if day_rpes and max(day_rpes) >= 9:
            s.high_rpe_days.append(d)
    s.high_rpe_days.sort()

    # Food, by athlete-local day from `logged_at`.
    days = food_days_payload(db, user_id, ws, end_exclusive)
    complete_cals, complete_pros, complete_cars, complete_fats = [], [], [], []
    for ds, row in days.items():
        s.food_logs_count += int(row["entries"] or 0)
        s.daily_calories[ds] = row["calories"] if row["calories"] is not None else 0.0
        s.food_by_date[ds] = {
            "entries": int(row["entries"] or 0),
            "calories": row["calories"],
            "protein": row["protein"],
            "carbs": row["carbs"],
            "fats": row["fats"],
            "status": row["status"],
            "complete": row["complete"],
        }
        if not row["complete"]:
            s.food_partial_days += 1
            continue
        if row["calories"] is not None:
            complete_cals.append(row["calories"])
        if row["protein"] is not None:
            complete_pros.append(row["protein"])
        if row["carbs"] is not None:
            complete_cars.append(row["carbs"])
        if row["fats"] is not None:
            complete_fats.append(row["fats"])

    s.food_days = len(days)
    s.food_complete_days = len(days) - s.food_partial_days
    if complete_cals:
        s.avg_calories = _safe_avg(complete_cals)
        s.avg_protein = _safe_avg(complete_pros)
        s.avg_carbs = _safe_avg(complete_cars)
        s.avg_fats = _safe_avg(complete_fats)
    else:
        # No confirmed day. An average over partial days is not an estimate
        # of what David ate, it is an estimate of what he remembered to log,
        # and the report would read it as the former.
        s.macro_average_unavailable = (
            "no day was confirmed fully logged, so a weekly average would "
            "describe logging habits rather than intake"
        )

    return s


def collect_fitness_daily(db: Session, user_id: str, ws: date, we: date) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT log_date, chat_count, food_entries, workout_sessions, notes_created,
                   total_calories, total_protein, total_carbs, total_fats, total_sets, total_reps
            FROM fitness_daily_log
            WHERE user_id = :uid AND log_date BETWEEN :ws AND :we
            ORDER BY log_date ASC
        """),
        {"uid": user_id, "ws": ws, "we": we},
    ).all()
    return [
        {
            "date": r.log_date.isoformat(),
            "chat_count": r.chat_count,
            "food_entries": r.food_entries,
            "workout_sessions": r.workout_sessions,
            "notes_created": r.notes_created,
            "total_calories": float(r.total_calories) if r.total_calories is not None else None,
            "total_protein": float(r.total_protein) if r.total_protein is not None else None,
            "total_carbs": float(r.total_carbs) if r.total_carbs is not None else None,
            "total_fats": float(r.total_fats) if r.total_fats is not None else None,
            "total_sets": r.total_sets,
            "total_reps": r.total_reps,
        }
        for r in rows
    ]


def collect_week(db: Session, user_id: str, ws: date, we: date) -> WeeklyDataset:
    return WeeklyDataset(
        user_id=user_id,
        week_start=ws,
        week_end=we,
        recovery=collect_recovery(db, user_id, ws, we),
        activity=collect_activity(db, user_id, ws, we),
        fitness_daily=collect_fitness_daily(db, user_id, ws, we),
    )
