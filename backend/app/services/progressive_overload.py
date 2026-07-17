"""
Progressive Overload — the single progression brain.

ONE engine, ONE table. Every weight suggestion (in-session coaching, the
/weight-suggestion endpoint, and the workout-detail enrichment) flows through
`compute_progression()`, which reads real logged sets from `workout_log`.

History: there used to be two engines. This module used to read a separate
`exercise_history` table that nothing ever populated, so its RPE-trend and
recovery logic was silently inert; meanwhile workout_session_service had its
own flat-increment logic reading `workout_log`. They've been unified here:
flat, lifter-friendly increments (the +5/+10 that barbell lifters actually
use), RPE-gated, with recovery used to *hold* weight on poor-recovery days.
"""

from typing import Optional, Dict, List, Tuple
from datetime import date
from sqlalchemy import text
from sqlalchemy.orm import Session


def _min_target_reps(target_reps) -> int:
    """Lower end of a rep target ("8-10" -> 8, "10" -> 10)."""
    s = str(target_reps)
    if "-" in s:
        try:
            return int(s.split("-")[0])
        except (TypeError, ValueError):
            return 8
    try:
        return int(s)
    except (TypeError, ValueError):
        return 8


def fetch_last_session(db: Session, user_id: str, exercise_name: str) -> Optional[Dict]:
    """Most recent logged session's sets for one exercise, from `workout_log`.

    Scoped strictly to `exercise_name` (matched against workout_log.exercise_id,
    case-insensitive) so a machine variant pulls only its own history. Skipped
    sets are excluded. Returns {date, weights[], reps[], avg_rpe} or None.
    """
    rows = db.execute(text("""
        SELECT session_date, weight, reps, rpe
        FROM workout_log
        WHERE user_id = :uid
          AND LOWER(exercise_id) = LOWER(:name)
          AND session_date IS NOT NULL
          AND COALESCE(skipped, false) = false
        ORDER BY session_date DESC, created_at DESC
        LIMIT 40
    """), {"uid": user_id, "name": exercise_name}).fetchall()

    if not rows:
        return None

    by_date: Dict[date, List[Dict]] = {}
    for r in rows:
        by_date.setdefault(r.session_date, []).append({
            "weight": float(r.weight) if r.weight is not None else 0.0,
            "reps": r.reps,
            "rpe": r.rpe if r.rpe is not None else 7,
        })

    last_date = max(by_date.keys())
    sets = by_date[last_date]
    return {
        "date": str(last_date),
        "weights": [s["weight"] for s in sets],
        "reps": [s["reps"] for s in sets if s["reps"] is not None],
        "avg_rpe": sum(s["rpe"] for s in sets) / len(sets),
    }


def get_recovery_factor(recovery_data: Optional[Dict]) -> Tuple[float, str]:
    """Recovery multiplier from HRV, sleep, and soreness.

    Returns (factor, reason). factor < 1.0 means "recovery is down" — the
    progression logic uses that to hold weight rather than add. > 1.0 is unused
    by the flat-increment model but kept for callers that read it.
    """
    if not recovery_data:
        return 1.0, "no recovery data"

    reasons: List[str] = []
    factor = 1.0

    soreness = recovery_data.get("soreness_level")
    if soreness:
        if soreness >= 8:
            factor *= 0.90
            reasons.append(f"high soreness ({soreness}/10)")
        elif soreness >= 6:
            factor *= 0.95
            reasons.append(f"moderate soreness ({soreness}/10)")
        elif soreness <= 3:
            factor *= 1.02
            reasons.append(f"low soreness ({soreness}/10)")

    sleep_hours = recovery_data.get("sleep_hours")
    if sleep_hours:
        if sleep_hours < 6:
            factor *= 0.95
            reasons.append(f"poor sleep ({sleep_hours:g}h)")
        elif sleep_hours >= 8:
            factor *= 1.02
            reasons.append(f"good sleep ({sleep_hours:g}h)")

    hrv = recovery_data.get("hrv")
    if hrv:
        if hrv < 30:
            factor *= 0.95
            reasons.append("low HRV")
        elif hrv > 60:
            factor *= 1.02
            reasons.append("high HRV")

    return factor, ", ".join(reasons) if reasons else "recovery normal"


def _round_plate(weight: float) -> float:
    """Round to the nearest real plate jump: 5 lb above 100, else 2.5 lb."""
    if weight >= 100:
        return round(weight / 5) * 5
    return round(weight / 2.5) * 2.5


def compute_progression(
    last_session: Optional[Dict],
    target_reps,
    exercise_name: str,
    is_deload: bool = False,
    recovery_data: Optional[Dict] = None,
) -> Dict:
    """THE progression brain. Flat-increment, RPE-gated, recovery-aware.

    Returns {suggested_weight, note, confidence, ask_user, last_session}.
    Recovery never inflates a jump — at most it downgrades an "add" to a "hold".
    """
    if not last_session or not last_session.get("weights"):
        return {
            "suggested_weight": None,
            "note": "First time — start conservative at RPE 7.",
            "confidence": "none",
            "ask_user": True,
            "last_session": last_session,
        }

    weights = last_session["weights"]
    avg_weight = sum(weights) / len(weights)
    avg_rpe = last_session["avg_rpe"]
    reps = last_session.get("reps") or []
    min_reps = min(reps) if reps else 0
    min_target = _min_target_reps(target_reps)

    is_lower_body = any(
        kw in exercise_name.lower()
        for kw in ["squat", "deadlift", "leg", "lunge", "hip"]
    )
    increment = 10 if is_lower_body else 5

    recovery_factor, recovery_reason = get_recovery_factor(recovery_data)
    poor_recovery = recovery_factor < 0.95

    if avg_rpe < 7.5 and min_reps >= min_target:
        if poor_recovery:
            suggested = avg_weight
            note = f"Last set felt easy (RPE {avg_rpe:.1f}) — holding, {recovery_reason}."
        else:
            suggested = avg_weight + increment
            note = f"Last session felt easy (RPE {avg_rpe:.1f}). Adding {increment}lbs."
    elif avg_rpe >= 8.5:
        suggested = avg_weight
        note = f"Last session was tough (RPE {avg_rpe:.1f}). Maintaining weight."
    elif min_reps < min_target:
        suggested = avg_weight
        note = f"Focus on hitting full reps at {avg_weight:.0f}lbs."
    elif poor_recovery:
        suggested = avg_weight
        note = f"Holding at {avg_weight:.0f}lbs — {recovery_reason}."
    else:
        suggested = avg_weight + 2.5
        note = f"Solid progression from {avg_weight:.0f}lbs."

    if is_deload:
        suggested = round((suggested * 0.6) / 5) * 5
        note = "DELOAD WEEK — 60% of working weight, halved sets. " + note
    else:
        suggested = _round_plate(suggested)

    return {
        "suggested_weight": suggested,
        "note": note,
        "confidence": "high",
        "ask_user": False,
        "last_session": last_session,
    }


def get_morning_recovery(db: Session, user_id: str, on_date: Optional[date] = None) -> Dict:
    """Morning recovery snapshot for weight gating.

    Deliberately uses the MORNING reading, not whatever an intraday HealthKit
    sync last wrote: HRV comes from the canonical `hrv_morning` metric (iOS
    stamps it ~6 AM, averaging 4-10 AM samples — never updated later in the day),
    falling back to the earliest plain `hrv` sample of the day, then to the
    daily_recovery_log value. Sleep and soreness are morning-anchored already
    (sleep can't change intraday; soreness is logged by hand).

    Returns {hrv, heart_rate, sleep_hours, soreness_level}.
    """
    on_date = on_date or date.today()

    base = db.execute(text("""
        SELECT hrv, heart_rate, sleep_hours, soreness_level
        FROM daily_recovery_log
        WHERE user_id = :uid AND log_date = :d
    """), {"uid": user_id, "d": on_date}).fetchone()

    sleep_hours = base.sleep_hours if base else None
    soreness = base.soreness_level if base else None
    heart_rate = base.heart_rate if base else None

    # Morning HRV from the granular metrics table (matched on the ET calendar day).
    row = db.execute(text("""
        SELECT value
        FROM health_metric
        WHERE user_id = :uid
          AND metric_type IN ('hrv_morning', 'hrv')
          AND DATE(recorded_at AT TIME ZONE 'America/New_York') = :d
        ORDER BY
          CASE metric_type WHEN 'hrv_morning' THEN 0 ELSE 1 END,
          recorded_at ASC
        LIMIT 1
    """), {"uid": user_id, "d": on_date}).fetchone()

    if row and row.value is not None:
        hrv = float(row.value)
    elif base and base.hrv is not None:
        hrv = float(base.hrv)
    else:
        hrv = None

    return {
        "hrv": hrv,
        "heart_rate": float(heart_rate) if heart_rate is not None else None,
        "sleep_hours": float(sleep_hours) if sleep_hours is not None else None,
        "soreness_level": int(soreness) if soreness is not None else None,
    }


def suggest_weight(
    db: Session,
    user_id: str,
    exercise_name: str,
    target_reps,
    recovery_data: Optional[Dict] = None,
    starting_weight: Optional[float] = None,
    is_deload: bool = False,
) -> Dict:
    """Route-facing wrapper around `compute_progression` (reads `workout_log`).

    Keeps the field contract the /weight-suggestion endpoint and workout-detail
    enrichment expect: suggested_weight, confidence, reasoning, progression_note,
    ask_user, last_session, history_data.
    """
    last = fetch_last_session(db, user_id, exercise_name)

    # No history but a template starting weight is configured — use it.
    if not last and starting_weight:
        suggested = float(starting_weight)
        if is_deload:
            suggested = round((suggested * 0.6) / 5) * 5
            reasoning = "Using template starting weight (deload — 60%)."
        else:
            reasoning = "Using template starting weight."
        return {
            "suggested_weight": suggested,
            "confidence": "medium",
            "reasoning": reasoning,
            "progression_note": reasoning,
            "ask_user": False,
            "last_session": None,
            "history_data": {"previous_avg": None, "last_rpe": None, "trend": None},
        }

    prog = compute_progression(last, target_reps, exercise_name, is_deload, recovery_data)
    prev_avg = (sum(last["weights"]) / len(last["weights"])) if last and last.get("weights") else None
    return {
        "suggested_weight": prog["suggested_weight"],
        "confidence": prog["confidence"],
        "reasoning": prog["note"],
        "progression_note": prog["note"],
        "ask_user": prog["ask_user"],
        "last_session": prog["last_session"],
        "history_data": {
            "previous_avg": round(prev_avg, 1) if prev_avg is not None else None,
            "last_rpe": round(last["avg_rpe"], 1) if last else None,
            "trend": None,
        },
    }


def get_deload_state(db: Session, user_id: str, on_date: date) -> Dict:
    """Whether `on_date` falls in the deload week of the user's active phase.

    A phase has an optional `deload_week` (1-indexed week within the phase). If
    the date's week-of-phase matches, is_deload=True with phase context.
    """
    row = db.execute(text("""
        SELECT id, name, start_date, end_date, duration_weeks, deload_week
        FROM fitness_phase
        WHERE user_id = :user_id
          AND start_date IS NOT NULL
          AND :d >= start_date
          AND (end_date IS NULL OR :d <= end_date)
        ORDER BY start_date DESC
        LIMIT 1
    """), {"user_id": user_id, "d": on_date}).fetchone()

    if not row:
        return {"is_deload": False, "phase_id": None, "phase_name": None,
                "week_of_phase": None, "deload_week": None}

    phase = dict(row._mapping)
    week_of_phase = ((on_date - phase["start_date"]).days // 7) + 1
    deload_week = phase.get("deload_week")
    is_deload = bool(deload_week and week_of_phase == int(deload_week))

    return {
        "is_deload": is_deload,
        "phase_id": phase["id"],
        "phase_name": phase["name"],
        "week_of_phase": week_of_phase,
        "deload_week": deload_week,
    }


def get_starting_weight_suggestion(
    db: Session,
    user_id: str,
    exercise_name: str,
    template_starting_weights: Optional[Dict] = None,
) -> Optional[float]:
    """Starting weight: template config first, then last logged set, else None."""
    if template_starting_weights and exercise_name in template_starting_weights:
        return template_starting_weights[exercise_name]

    last = fetch_last_session(db, user_id, exercise_name)
    if last and last.get("weights"):
        return sum(last["weights"]) / len(last["weights"])
    return None
