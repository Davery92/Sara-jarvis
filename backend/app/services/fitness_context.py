"""
Fitness Context Provider

Builds a compact context snippet for Sara's main chat with today's nutrition
plan, macros consumed so far, and remaining budget. Enables natural food/meal
conversations without requiring the user to use a separate fitness chat.
"""

import json
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timezone import today as local_today
from app.services.phase_resolution import get_effective_phase

logger = logging.getLogger(__name__)


async def get_fitness_context(user_id: str, db: Session) -> Optional[str]:
    """
    Build a compact fitness context string for injection into Sara's system prompt.

    Returns None if no active phase/goals exist (user has no fitness plan).
    """
    try:
        today = local_today()

        # 1. Resolve the dated phase of the approved active program.
        phase_row = get_effective_phase(db, user_id, today)

        # Fall back to fitness_goals if no active phase
        if not phase_row:
            goals_row = db.execute(text("""
                SELECT calories, protein, carbs, fats
                FROM fitness_goals WHERE user_id = :uid
            """), {"uid": user_id}).fetchone()
            if not goals_row:
                return None
            goals = dict(goals_row._mapping)
            target = {
                "calories": goals.get("calories"),
                "protein": goals.get("protein"),
                "carbs": goals.get("carbs"),
                "fat": goals.get("fats"),
            }
            phase_name = None
            is_training = False
        else:
            phase = dict(phase_row)
            phase_name = phase["name"]

            # Determine training vs rest day — shared definition so this never
            # contradicts the morning brief (session logged OR scheduled template).
            from app.services.training_day import is_training_day
            is_training = is_training_day(db, user_id, today)["is_training_day"]

            if is_training:
                target = {
                    "calories": phase.get("calories_training_day") or phase.get("calories_target"),
                    "protein": phase.get("protein_target"),
                    "carbs": phase.get("carbs_training_day") or phase.get("carbs_target"),
                    "fat": phase.get("fat_training_day") or phase.get("fat_target"),
                }
            else:
                target = {
                    "calories": phase.get("calories_rest_day") or phase.get("calories_target"),
                    "protein": phase.get("protein_target"),
                    "carbs": phase.get("carbs_rest_day") or phase.get("carbs_target"),
                    "fat": phase.get("fat_rest_day") or phase.get("fat_target"),
                }

        # 2. Get today's food log totals
        food_totals = db.execute(text("""
            SELECT
                COALESCE(SUM(calories), 0) as total_cal,
                COALESCE(SUM(protein), 0) as total_protein,
                COALESCE(SUM(carbs), 0) as total_carbs,
                COALESCE(SUM(fats), 0) as total_fat,
                COUNT(*) as meal_count
            FROM food_log
            WHERE user_id = :uid AND DATE(logged_at) = :d
        """), {"uid": user_id, "d": today}).fetchone()

        eaten = {
            "calories": round(food_totals.total_cal or 0),
            "protein": round(food_totals.total_protein or 0),
            "carbs": round(food_totals.total_carbs or 0),
            "fat": round(food_totals.total_fat or 0),
        }
        meals_logged = food_totals.meal_count or 0

        # 3. Get today's meals for detail
        meals_rows = db.execute(text("""
            SELECT meal_type, food_items, calories, protein, carbs, fats
            FROM food_log
            WHERE user_id = :uid AND DATE(logged_at) = :d
            ORDER BY logged_at
        """), {"uid": user_id, "d": today}).fetchall()

        meal_lines = []
        for m in meals_rows:
            food_items = m.food_items
            if isinstance(food_items, str):
                try:
                    food_items = json.loads(food_items)
                except Exception:
                    food_items = []
            if isinstance(food_items, list):
                names = [item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in food_items]
                food_str = ", ".join(names) if names else "Unknown"
            else:
                food_str = str(food_items) if food_items else "Unknown"
            meal_lines.append(
                f"  - {m.meal_type or 'meal'}: {food_str} ({int(m.calories or 0)} cal, "
                f"{int(m.protein or 0)}p/{int(m.carbs or 0)}c/{int(m.fats or 0)}f)"
            )

        # 4. Compute remaining
        remaining = {}
        for key in ["calories", "protein", "carbs", "fat"]:
            t = target.get(key)
            if t:
                remaining[key] = round(t - eaten[key])
            else:
                remaining[key] = None

        # 5. Build compact context
        lines = ["## David's Nutrition Plan (Today)"]

        if phase_name:
            day_type = "Training Day" if is_training else "Rest Day"
            lines.append(f"**Phase:** {phase_name} | **Today:** {day_type}")

        lines.append(
            f"**Targets:** {_fmt(target['calories'])} cal | "
            f"{_fmt(target['protein'])}g protein | "
            f"{_fmt(target['carbs'])}g carbs | "
            f"{_fmt(target['fat'])}g fat"
        )

        if meals_logged > 0:
            lines.append(
                f"**Eaten so far:** {eaten['calories']} cal | "
                f"{eaten['protein']}g protein | "
                f"{eaten['carbs']}g carbs | "
                f"{eaten['fat']}g fat"
            )
            lines.append(
                f"**Remaining:** {_fmt(remaining['calories'])} cal | "
                f"{_fmt(remaining['protein'])}g protein | "
                f"{_fmt(remaining['carbs'])}g carbs | "
                f"{_fmt(remaining['fat'])}g fat"
            )
            if meal_lines:
                lines.append("**Meals today:**")
                lines.extend(meal_lines)
        else:
            lines.append("**No meals logged yet today.**")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Failed to build fitness context: {e}")
        return None


def _fmt(val) -> str:
    """Format a numeric value, returning '—' if None."""
    if val is None:
        return "—"
    return str(round(val))
