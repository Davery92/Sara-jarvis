"""
Progressive Overload AI Service

Provides intelligent weight suggestions based on:
- Exercise performance history (last 4 weeks)
- RPE (Rate of Perceived Exertion) trends
- Recovery metrics (HRV, soreness, sleep)
- Progressive overload principles
"""

from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta, date
from sqlalchemy import text
from sqlalchemy.orm import Session


def analyze_exercise_history(
    db: Session,
    user_id: str,
    exercise_name: str,
    weeks: int = 4
) -> Dict:
    """
    Analyze recent exercise performance history

    Returns:
        dict with avg_weight, avg_rpe, trend, recent_sessions
    """
    cutoff_date = date.today() - timedelta(weeks=weeks)

    # Get recent exercise history
    query = text("""
        SELECT
            performance_date,
            avg_weight,
            total_sets,
            total_reps,
            avg_rpe
        FROM exercise_history
        WHERE user_id = :user_id
          AND exercise_name = :exercise_name
          AND performance_date >= :cutoff_date
        ORDER BY performance_date DESC
        LIMIT 10
    """)

    results = db.execute(query, {
        "user_id": user_id,
        "exercise_name": exercise_name,
        "cutoff_date": cutoff_date
    }).fetchall()

    if not results:
        return {
            "has_history": False,
            "avg_weight": None,
            "avg_rpe": None,
            "trend": "no_data",
            "recent_sessions": []
        }

    # Calculate averages
    recent_sessions = [dict(row._mapping) for row in results]
    avg_weight = sum(s['avg_weight'] or 0 for s in recent_sessions) / len(recent_sessions)
    avg_rpe = sum(s['avg_rpe'] or 0 for s in recent_sessions) / len(recent_sessions)

    # Determine trend (last 3 vs previous 3)
    if len(recent_sessions) >= 6:
        recent_3_weight = sum(s['avg_weight'] or 0 for s in recent_sessions[:3]) / 3
        previous_3_weight = sum(s['avg_weight'] or 0 for s in recent_sessions[3:6]) / 3

        if recent_3_weight > previous_3_weight * 1.05:
            trend = "increasing"
        elif recent_3_weight < previous_3_weight * 0.95:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    return {
        "has_history": True,
        "avg_weight": round(avg_weight, 1),
        "avg_rpe": round(avg_rpe, 1),
        "trend": trend,
        "recent_sessions": recent_sessions
    }


def get_recovery_factor(recovery_data: Optional[Dict]) -> Tuple[float, str]:
    """
    Calculate recovery factor based on HRV, sleep, and soreness

    Returns:
        (factor: float, reason: str)
        factor: 0.9 (reduce), 1.0 (maintain), 1.05 (increase)
    """
    if not recovery_data:
        return 1.0, "No recovery data available"

    reasons = []
    factor = 1.0

    # Soreness level (most important)
    soreness = recovery_data.get('soreness_level')
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

    # Sleep quality
    sleep_hours = recovery_data.get('sleep_hours')
    if sleep_hours:
        if sleep_hours < 6:
            factor *= 0.95
            reasons.append(f"poor sleep ({sleep_hours}h)")
        elif sleep_hours >= 8:
            factor *= 1.02
            reasons.append(f"good sleep ({sleep_hours}h)")

    # HRV (if available)
    hrv = recovery_data.get('hrv')
    if hrv:
        # Assuming typical HRV ranges (simplified)
        if hrv < 30:
            factor *= 0.95
            reasons.append("low HRV")
        elif hrv > 60:
            factor *= 1.02
            reasons.append("high HRV")

    reason = ", ".join(reasons) if reasons else "recovery is normal"
    return factor, reason


def suggest_weight(
    db: Session,
    user_id: str,
    exercise_name: str,
    target_reps: int,
    recovery_data: Optional[Dict] = None,
    starting_weight: Optional[float] = None
) -> Dict:
    """
    Suggest weight for next set based on progressive overload principles

    Returns:
        dict with suggested_weight, confidence, reasoning
    """
    # Analyze exercise history
    history = analyze_exercise_history(db, user_id, exercise_name)

    # If no history and no starting weight, return placeholder
    if not history["has_history"] and not starting_weight:
        return {
            "suggested_weight": None,
            "confidence": "none",
            "reasoning": "No exercise history available. Please enter a starting weight.",
            "ask_user": True
        }

    # Get recovery factor
    recovery_factor, recovery_reason = get_recovery_factor(recovery_data)

    # Determine base weight
    if history["has_history"]:
        base_weight = history["avg_weight"]
        last_rpe = history["avg_rpe"]

        # Progressive overload logic based on RPE
        if last_rpe and last_rpe <= 6:
            # RPE too low - increase weight significantly
            adjustment = 1.05  # 5% increase
            reasoning_parts = [f"last RPE was low ({last_rpe:.1f})"]
        elif last_rpe and last_rpe <= 7:
            # RPE moderate - small increase
            adjustment = 1.025  # 2.5% increase
            reasoning_parts = [f"last RPE was moderate ({last_rpe:.1f})"]
        elif last_rpe and last_rpe >= 9:
            # RPE too high - maintain or reduce
            adjustment = 0.975  # 2.5% decrease
            reasoning_parts = [f"last RPE was high ({last_rpe:.1f})"]
        else:
            # RPE good (7-8) - maintain
            adjustment = 1.0
            reasoning_parts = [f"last RPE was good ({last_rpe:.1f})"]

        # Apply trend adjustment
        if history["trend"] == "decreasing":
            adjustment *= 0.975
            reasoning_parts.append("performance trend declining")
        elif history["trend"] == "increasing":
            adjustment *= 1.01
            reasoning_parts.append("performance trend improving")

        confidence = "high"
    else:
        # Use starting weight
        base_weight = starting_weight
        adjustment = 1.0
        reasoning_parts = ["using starting weight"]
        confidence = "medium"

    # Apply recovery factor
    final_adjustment = adjustment * recovery_factor
    suggested = base_weight * final_adjustment

    # Add recovery reasoning
    if recovery_factor != 1.0:
        reasoning_parts.append(recovery_reason)

    # Round to nearest 2.5 lbs (or 5 lbs for heavy weights)
    if suggested >= 100:
        suggested = round(suggested / 5) * 5
    else:
        suggested = round(suggested / 2.5) * 2.5

    reasoning = "Based on: " + ", ".join(reasoning_parts)

    return {
        "suggested_weight": suggested,
        "confidence": confidence,
        "reasoning": reasoning,
        "ask_user": False,
        "history_data": {
            "previous_avg": base_weight if history["has_history"] else None,
            "last_rpe": history.get("avg_rpe"),
            "trend": history.get("trend")
        }
    }


def get_starting_weight_suggestion(
    db: Session,
    user_id: str,
    exercise_name: str,
    template_starting_weights: Optional[Dict] = None
) -> Optional[float]:
    """
    Get starting weight from fallback hierarchy:
    1. Template starting_weights (if configured)
    2. Historical data (if exists)
    3. None (ask user)
    """
    # Check template starting weights
    if template_starting_weights and exercise_name in template_starting_weights:
        return template_starting_weights[exercise_name]

    # Check if we have any historical data for this exercise
    query = text("""
        SELECT avg_weight
        FROM exercise_history
        WHERE user_id = :user_id AND exercise_name = :exercise_name
        ORDER BY performance_date DESC
        LIMIT 1
    """)

    result = db.execute(query, {
        "user_id": user_id,
        "exercise_name": exercise_name
    }).fetchone()

    if result and result.avg_weight:
        return result.avg_weight

    # No data available - user needs to provide
    return None
