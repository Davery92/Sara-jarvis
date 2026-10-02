"""One implementation of the numbers Sara's older fitness surfaces report.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 18. Before this, five readers each did
their own arithmetic over the same tables and disagreed:

* `fitness_context.py` summed `food_log` by `DATE(logged_at)` in ET;
  `tools/fitness/summary.py` summed it by `DATE(created_at)` in **UTC**. Those
  are two different days and two different totals, in the same chat turn.
* `health_consolidation/data_collector.py` set `workouts_count = len(set_rows)`
  — the field named "workouts" held the number of SETS.
* Three places computed volume as `SUM(weight * reps)` over the legacy
  integer `weight` column: a 102.5 kg lift counted as 102, a dumbbell press
  counted one hand, and an assisted pull-up counted the assistance as work.
* `data_collector` dropped a body weight whose `weight_unit` was `kg`
  instead of converting it, so a kg-logging week reported no weight data.

These functions return the **old shapes**, so the readers keep their response
contracts. What changes is that there is now one place the numbers come from,
and it is the same place `FitnessStateV1` comes from.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.fitness_coach import Unit, convert
from app.services.fitness.data_access import (
    _require_user,
    athlete_zone,
    effective_load,
    load_food_days,
    load_sets,
    load_training_sessions,
)

logger = logging.getLogger(__name__)

#: The unit every legacy consumer displays volume and bodyweight in. Pounds,
#: because `weight_trend`, the iOS app and the dashboard were all written
#: against pounds and `LEGACY_METRIC_UNITS` pins the `weight` metric there.
LEGACY_DISPLAY_UNIT = Unit.LB


def athlete_timezone(db: Session, user_id: str) -> str:
    from app.services.fitness.profile import profile_timezone
    try:
        return profile_timezone(db, user_id)
    except Exception:
        return "America/New_York"


def athlete_local_today(db: Session, user_id: str) -> date:
    """The athlete's today, from their own profile timezone.

    Not `datetime.now(timezone.utc).date()`, which is what the summary tool
    used: from 20:00 ET onward that is tomorrow, so "today's nutrition" came
    back empty every evening — the hours David is most likely to ask. And not
    the global ET helper either, because the athlete's zone is a profile
    field now (Step 8) and the state is cut on it.
    """
    return datetime.now(athlete_zone(athlete_timezone(db, user_id))).date()


# ─────────────────────────────────────────────────────────────────────────
# Nutrition
# ─────────────────────────────────────────────────────────────────────────

def nutrition_day(
    db: Session, user_id: str, day: Optional[date] = None,
) -> Dict[str, Any]:
    """Targets, intake and remainder for one athlete-local day.

    The day comes from `food_log.logged_at` (naive ET wall-clock), never from
    `created_at` (naive UTC insert time). Those differ for every meal logged
    before 20:00 ET and for every meal entered after the fact.

    Targets come from `resolve_targets`, which is the only thing that knows
    about dated revisions and the training/rest split — so this cannot
    disagree with the Coach API about what today prescribes.
    """
    uid = _require_user(user_id)
    tz_name = athlete_timezone(db, uid)
    target_day = day or athlete_local_today(db, uid)

    from app.services.fitness.targets import resolve_targets
    resolved = resolve_targets(db, uid, target_day)
    values = resolved.values

    target = {
        "calories": values.calories,
        "protein": values.protein_g,
        "carbs": values.carbs_g,
        "fat": values.fat_g,
    }

    days = load_food_days(db, uid, target_day, target_day + timedelta(days=1),
                          timezone_name=tz_name)
    food = days.get(target_day)

    eaten = {
        "calories": round(food.calories) if food and food.calories is not None else 0,
        "protein": round(food.protein_g) if food and food.protein_g is not None else 0,
        "carbs": round(food.carbs_g) if food and food.carbs_g is not None else 0,
        "fat": round(food.fat_g) if food and food.fat_g is not None else 0,
    }
    # Which fields were actually recorded, so a consumer can tell "0 g fat
    # eaten" from "fat was never logged". Summing NULLs to zero and then
    # subtracting is how a day with unknown fat reports the full fat budget
    # still available.
    #
    # Re-keyed to the OUTPUT names. `load_food_days` counts under the
    # `food_log` column names (`fats`), while everything above the data layer
    # uses `fat` — so a caller checking `known["fat"]` got nothing and a
    # logged fat value rendered as unknown. Both keys are kept so a consumer
    # written against either one works.
    raw_known = dict(food.known_fields) if food else {}
    known = dict(raw_known)
    for column, field_name in (("fats", "fat"), ("protein", "protein_g"),
                               ("carbs", "carbs_g")):
        if column in raw_known:
            known.setdefault(field_name, raw_known[column])

    remaining = {
        key: (round(target[key] - eaten[key]) if target.get(key) else None)
        for key in ("calories", "protein", "carbs", "fat")
    }

    return {
        "date": target_day.isoformat(),
        "day_type": resolved.day_type.value,
        "target": target,
        "target_provenance": resolved.provenance.value,
        "phase_name": resolved.phase_name,
        "eaten": eaten,
        "known_fields": known,
        "remaining": remaining,
        "meal_count": food.meal_count if food else 0,
        "meals": _meal_rows(db, uid, target_day, tz_name),
        "has_estimated_items": bool(food.has_estimated_items) if food else False,
    }


def _meal_rows(
    db: Session, user_id: str, day: date, tz_name: str,
) -> List[Dict[str, Any]]:
    """The day's meals, resolved on the athlete's calendar.

    The bounds are computed in the athlete's zone and compared against the
    naive ET `logged_at` column, which is why this is a BETWEEN on naive
    timestamps rather than an `AT TIME ZONE` conversion: the column has no
    offset to convert from.
    """
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    rows = db.execute(text("""
        SELECT meal_type, food_items, calories, protein, carbs, fats, logged_at
        FROM food_log
        WHERE user_id = :uid AND logged_at >= :start AND logged_at < :end
        ORDER BY logged_at ASC
    """), {"uid": user_id, "start": start, "end": end}).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append({
            "meal_type": row.meal_type or "meal",
            "food": _food_names(row.food_items),
            "calories": float(row.calories) if row.calories is not None else None,
            "protein": float(row.protein) if row.protein is not None else None,
            "carbs": float(row.carbs) if row.carbs is not None else None,
            "fats": float(row.fats) if row.fats is not None else None,
            "time": row.logged_at.strftime("%H:%M") if row.logged_at else None,
        })
    return out


def _food_names(food_items: Any) -> str:
    items = food_items
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            items = []
    if isinstance(items, list):
        names = [
            item.get("name", str(item)) if isinstance(item, dict) else str(item)
            for item in items
        ]
        return ", ".join(n for n in names if n) or "Unknown"
    return str(items) if items else "Unknown"


def food_days_payload(
    db: Session, user_id: str, start: date, end: date,
) -> Dict[str, Dict[str, Any]]:
    """Per-day intake in `[start, end)`, keyed by ISO date.

    Carries `complete` and `known_fields` so a caller can average over days
    the athlete confirmed were fully logged. Averaging over every day that
    has any row counts a logged breakfast as a day's eating, which is how a
    cut looks like a crash diet in a weekly report.
    """
    uid = _require_user(user_id)
    tz_name = athlete_timezone(db, uid)
    days = load_food_days(db, uid, start, end, timezone_name=tz_name)

    statuses = _nutrition_statuses(db, uid, start, end)
    out: Dict[str, Dict[str, Any]] = {}
    for day, food in sorted(days.items()):
        out[day.isoformat()] = {
            "entries": food.meal_count,
            "calories": round(food.calories, 1) if food.calories is not None else None,
            "protein": round(food.protein_g, 1) if food.protein_g is not None else None,
            "carbs": round(food.carbs_g, 1) if food.carbs_g is not None else None,
            "fats": round(food.fat_g, 1) if food.fat_g is not None else None,
            "known_fields": dict(food.known_fields),
            "status": statuses.get(day, "unknown"),
            "complete": statuses.get(day) == "complete",
        }
    return out


def _nutrition_statuses(
    db: Session, user_id: str, start: date, end: date,
) -> Dict[date, str]:
    present = {
        r[0] for r in db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'daily_recovery_log'
        """)).fetchall()
    }
    if "nutrition_status" not in present:
        return {}
    rows = db.execute(text("""
        SELECT log_date, nutrition_status FROM daily_recovery_log
        WHERE user_id = :uid AND log_date >= :start AND log_date < :end
    """), {"uid": user_id, "start": start, "end": end}).fetchall()
    return {r.log_date: (r.nutrition_status or "unknown") for r in rows}


# ─────────────────────────────────────────────────────────────────────────
# Training
# ─────────────────────────────────────────────────────────────────────────

def training_window(
    db: Session, user_id: str, start: date, end: date,
) -> Dict[str, Any]:
    """Sessions, sets and tonnage over `[start, end)`.

    `sessions` counts de-duplicated training bouts, not set rows. The weekly
    health collector reported `workouts_count = len(set_rows)`, so a single
    session of 24 sets read as 24 workouts and the consolidation prompt was
    told David trained every day.

    `tonnage` uses the **effective** load — per-hand doubled, assisted and
    bodyweight excluded, machine stacks excluded, and an exercise whose load
    convention was never recorded excluded rather than assumed. The three
    legacy `SUM(weight * reps)` queries did none of that, and the integer
    `weight` column also dropped every fractional plate.
    """
    uid = _require_user(user_id)
    tz_name = athlete_timezone(db, uid)

    sessions = load_training_sessions(db, uid, start, end)
    sets = load_sets(db, uid, start, end, timezone_name=tz_name)

    from app.services.fitness.exercises import effective_load_for, get_exercise

    cache: Dict[str, Any] = {}
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    total_sets = 0
    working_sets = 0
    total_reps = 0
    tonnage_lb = 0.0
    excluded: Dict[str, int] = {}
    efforts: List[float] = []

    for row in sets:
        if not row.is_live:
            continue
        day = row.session_date or (row.logged_at.date() if row.logged_at else None)
        if day is None:
            continue
        total_sets += 1
        if row.is_working:
            working_sets += 1
        if row.reps:
            total_reps += int(row.reps)
        if row.rpe is not None:
            efforts.append(float(row.rpe))

        ref = None
        if row.exercise_library_id:
            if row.exercise_library_id not in cache:
                cache[row.exercise_library_id] = get_exercise(
                    db, uid, row.exercise_library_id
                )
            ref = cache[row.exercise_library_id]
        load, reason = effective_load_for(ref, row.load)

        if row.is_working and row.reps and load is not None:
            try:
                tonnage_lb += convert(load, row.load_unit, LEGACY_DISPLAY_UNIT) * int(row.reps)
            except Exception:
                excluded["unit_unknown"] = excluded.get("unit_unknown", 0) + 1
        elif row.is_working and row.reps:
            key = (reason or "no load recorded").split(" —")[0]
            excluded[key] = excluded.get(key, 0) + 1

        by_date.setdefault(day.isoformat(), []).append({
            "exercise_id": row.exercise_id,
            "set": row.set_index,
            # Both: the number the athlete typed, and what it actually moved.
            "weight": row.load,
            "weight_unit": row.load_unit.value,
            "effective_load": load,
            "reps": row.reps,
            "rpe": row.rpe,
            "rir": row.rir,
        })

    session_dates = sorted({
        s.session_date.isoformat() for s in sessions if s.session_date
    })
    completed = [s for s in sessions if s.status in ("completed", "complete")]

    return {
        "sessions": len(sessions),
        "sessions_completed": len(completed),
        "session_dates": session_dates,
        "days_trained": len(session_dates or by_date),
        "sets": total_sets,
        "working_sets": working_sets,
        "total_reps": total_reps,
        "tonnage": round(tonnage_lb, 1) if tonnage_lb else None,
        "tonnage_unit": LEGACY_DISPLAY_UNIT.value,
        # Named so a reader can see the tonnage is a floor, not a total.
        "sets_excluded_from_tonnage": excluded,
        "avg_rpe": round(sum(efforts) / len(efforts), 2) if efforts else None,
        "by_date": by_date,
        "session_rows": [
            {
                "key": s.key,
                "date": s.session_date.isoformat() if s.session_date else None,
                "status": s.status,
                "template_id": s.template_id,
                "was_planned": s.was_planned,
                "sets_completed": s.total_sets_completed,
            }
            for s in sessions
        ],
    }


def latest_working_set(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    """The most recently entered live working set, with its real load.

    The world brief rendered `wl.weight`, the legacy integer. A 102.5 kg
    squat was spoken as 102, and a 40 kg dumbbell press as 40 rather than
    80 — so the brief and the strength analytics described the same set
    differently.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT COALESCE(el.name, wl.exercise_id, 'Exercise') AS exercise_name,
               wl.exercise_library_id, wl.weight, wl.load_value, wl.load_unit,
               wl.reps, wl.created_at, wl.session_date
        FROM workout_log wl
        LEFT JOIN exercise_library el ON el.id = wl.exercise_library_id
        WHERE wl.user_id = :uid AND wl.voided_at IS NULL
          AND COALESCE(wl.skipped, false) = false
          AND wl.set_kind = 'working'
        ORDER BY wl.created_at DESC
        LIMIT 1
    """), {"uid": uid}).first()
    if row is None:
        return None

    load, unit = effective_load(row)
    from app.services.fitness.exercises import effective_load_for, get_exercise
    ref = get_exercise(db, uid, row.exercise_library_id) if row.exercise_library_id else None
    total, reason = effective_load_for(ref, load)

    return {
        "exercise_name": row.exercise_name,
        # What was recorded, which is what the athlete typed.
        "load": load,
        "load_unit": unit.value,
        # What it moved, when that is knowable. None with a reason otherwise —
        # a dumbbell press's per-hand number is not the load, and guessing
        # would be the error, not the omission.
        "effective_load": total,
        "effective_load_unavailable": reason if total is None else None,
        "reps": row.reps,
        "created_at": row.created_at,
        "session_date": row.session_date,
    }


# ─────────────────────────────────────────────────────────────────────────
# Body weight
# ─────────────────────────────────────────────────────────────────────────

def weight_window(
    db: Session, user_id: str, start: date, end: date,
) -> Dict[str, Any]:
    """Canonical body weight across `[start, end)`, in pounds, with coverage.

    Two things the weekly collector got wrong and this fixes:

    * it read `daily_recovery_log.body_weight` and **dropped** any row whose
      `weight_unit` was not `lbs`, so a week logged in kg reported no weight
      data at all rather than converting;
    * it reported `weight_delta` from the first and last rows in the window
      with no statement of how many days that spanned, so a delta between
      two readings five days apart read the same as one across a full week.
    """
    uid = _require_user(user_id)
    tz_name = athlete_timezone(db, uid)
    from app.services.fitness.observations import selected_series

    series = selected_series(db, uid, "weight", start, end, timezone_name=tz_name)
    daily: List[Dict[str, Any]] = []
    for day, chosen in sorted(series.items()):
        try:
            value = convert(chosen.value, chosen.unit, LEGACY_DISPLAY_UNIT)
        except Exception:
            continue
        daily.append({
            "date": day.isoformat(),
            "weight_lbs": round(value, 2),
            "source_count": chosen.candidate_count,
            "quality_flags": [f.value for f in chosen.quality_flags],
        })

    expected = max((end - start).days, 0)
    out: Dict[str, Any] = {
        "daily": daily,
        "observed_days": len(daily),
        "expected_days": expected,
        "unit": LEGACY_DISPLAY_UNIT.value,
        "start_lbs": None, "end_lbs": None, "delta_lbs": None,
        "delta_span_days": None,
    }
    if len(daily) >= 2:
        first, last = daily[0], daily[-1]
        out["start_lbs"] = first["weight_lbs"]
        out["end_lbs"] = last["weight_lbs"]
        out["delta_lbs"] = round(last["weight_lbs"] - first["weight_lbs"], 2)
        out["delta_span_days"] = (
            date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])
        ).days
    elif len(daily) == 1:
        # One reading is a weight, not a trend. Reporting delta 0 would say
        # "no change", which is a claim this cannot support.
        out["end_lbs"] = daily[0]["weight_lbs"]
    return out
