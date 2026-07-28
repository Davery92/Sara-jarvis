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
    if not rows:
        return s

    daily = []
    hrvs, rhrs, sleeps, weights = [], [], [], []
    for r in rows:
        rec = {
            "date": r.log_date.isoformat(),
            "hrv": r.hrv,
            "rhr": r.heart_rate,
            "sleep_hours": float(r.sleep_hours) if r.sleep_hours is not None else None,
            "body_weight_lbs": float(r.body_weight) if r.body_weight is not None and (r.weight_unit or "lbs") == "lbs" else None,
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
    if weights:
        s.weight_lbs_start = weights[0]
        s.weight_lbs_end = weights[-1]
        s.weight_delta_lbs = round(weights[-1] - weights[0], 2)

    return s


def collect_activity(db: Session, user_id: str, ws: date, we: date) -> ActivityStats:
    s = ActivityStats()

    # Workouts (set-level, aggregate to day-level)
    wo_rows = db.execute(
        text("""
            SELECT session_date, exercise_id, set_index, weight, reps, rpe, day_of_week
            FROM workout_log
            WHERE user_id = :uid AND session_date BETWEEN :ws AND :we
              AND COALESCE(skipped, false) = false
              AND voided_at IS NULL
            ORDER BY session_date ASC, set_index ASC
        """),
        {"uid": user_id, "ws": ws, "we": we},
    ).all()

    rpes = []
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in wo_rows:
        d = r.session_date.isoformat() if r.session_date else None
        if not d:
            continue
        by_date.setdefault(d, []).append({
            "exercise_id": r.exercise_id,
            "set": r.set_index,
            "weight": r.weight,
            "reps": r.reps,
            "rpe": r.rpe,
        })
        s.total_sets += 1
        if r.reps:
            s.total_reps += int(r.reps)
        if r.rpe is not None:
            rpes.append(int(r.rpe))

    s.workouts_count = len(wo_rows)
    s.workout_dates = sorted(by_date.keys())
    s.workout_days = len(s.workout_dates)
    s.workouts_by_date = by_date
    if rpes:
        s.avg_rpe = round(mean(rpes), 2)
        # Flag any day where the max set RPE was 9+
        for d, sets in by_date.items():
            day_rpes = [x["rpe"] for x in sets if x.get("rpe") is not None]
            if day_rpes and max(day_rpes) >= 9:
                s.high_rpe_days.append(d)
        s.high_rpe_days.sort()

    # Food logs (day-aggregate)
    food_rows = db.execute(
        text("""
            SELECT logged_at::date AS d,
                   COUNT(*)            AS entries,
                   SUM(calories)       AS cal,
                   SUM(protein)        AS pro,
                   SUM(carbs)          AS car,
                   SUM(fats)           AS fat
            FROM food_log
            WHERE user_id = :uid AND logged_at::date BETWEEN :ws AND :we
            GROUP BY logged_at::date
            ORDER BY d ASC
        """),
        {"uid": user_id, "ws": ws, "we": we},
    ).all()

    cals, pros, cars, fats = [], [], [], []
    for r in food_rows:
        ds = r.d.isoformat()
        cal = float(r.cal) if r.cal is not None else 0.0
        pro = float(r.pro) if r.pro is not None else 0.0
        car = float(r.car) if r.car is not None else 0.0
        fat = float(r.fat) if r.fat is not None else 0.0
        s.food_logs_count += int(r.entries or 0)
        s.daily_calories[ds] = round(cal, 1)
        s.food_by_date[ds] = {"entries": int(r.entries or 0), "calories": round(cal, 1),
                              "protein": round(pro, 1), "carbs": round(car, 1), "fats": round(fat, 1)}
        if cal: cals.append(cal)
        if pro: pros.append(pro)
        if car: cars.append(car)
        if fat: fats.append(fat)

    s.food_days = len(food_rows)
    s.avg_calories = _safe_avg(cals)
    s.avg_protein = _safe_avg(pros)
    s.avg_carbs = _safe_avg(cars)
    s.avg_fats = _safe_avg(fats)

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
