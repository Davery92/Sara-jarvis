"""
Fitness Summary Tool
Provides on-demand fitness status for regular Sara chat
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import json


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class FitnessSummaryTool(BaseTool):
    """Get current fitness status and recent activity"""

    @property
    def name(self) -> str:
        return "fitness_summary"

    @property
    def description(self) -> str:
        return "Get user's current fitness status: today's nutrition, recent workouts (last 3-7 days), upcoming scheduled workouts, and recovery metrics. Use this when the user asks about their fitness, workouts, nutrition, or training progress."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to look back for recent workouts (default: 3)",
                    "default": 3
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get comprehensive fitness summary"""
        days_back = kwargs.get("days_back", 3)

        db = get_fitness_db()
        today = datetime.now(timezone.utc).date()
        lookback_date = today - timedelta(days=days_back)

        try:
            summary = {}

            # === TODAY'S NUTRITION ===
            nutrition_sql = text("""
                SELECT
                    meal_type,
                    food_items,
                    calories,
                    protein,
                    carbs,
                    fats,
                    created_at
                FROM food_log
                WHERE user_id = :user_id
                AND DATE(created_at) = :today
                ORDER BY created_at DESC
            """)

            nutrition_result = db.execute(nutrition_sql, {
                "user_id": user_id,
                "today": today
            })

            meals = []
            total_cals = 0
            total_protein = 0
            total_carbs = 0
            total_fats = 0

            for row in nutrition_result.fetchall():
                # Parse food_items JSON to get food names
                food_items = row.food_items
                if isinstance(food_items, str):
                    try:
                        food_items = json.loads(food_items)
                    except:
                        food_items = []

                # Extract food names from items
                if isinstance(food_items, list):
                    food_names = [item.get('name', str(item)) if isinstance(item, dict) else str(item) for item in food_items]
                    food_display = ", ".join(food_names) if food_names else "Unknown"
                else:
                    food_display = str(food_items) if food_items else "Unknown"

                meal = {
                    "meal_type": row.meal_type,
                    "food": food_display,
                    "calories": row.calories or 0,
                    "protein": row.protein or 0,
                    "carbs": row.carbs or 0,
                    "fats": row.fats or 0,
                    "time": row.created_at.strftime("%H:%M") if row.created_at else None
                }
                meals.append(meal)
                total_cals += row.calories or 0
                total_protein += row.protein or 0
                total_carbs += row.carbs or 0
                total_fats += row.fats or 0

            summary["today_nutrition"] = {
                "meals": meals,
                "totals": {
                    "calories": round(total_cals, 1),
                    "protein": round(total_protein, 1),
                    "carbs": round(total_carbs, 1),
                    "fats": round(total_fats, 1)
                },
                "meal_count": len(meals)
            }

            # === RECENT WORKOUTS ===
            recent_workouts_sql = text("""
                SELECT DISTINCT
                    w.id,
                    w.title,
                    w.phase,
                    w.week,
                    w.day_of_week,
                    w.status,
                    w.created_at,
                    COUNT(wl.id) as sets_logged,
                    SUM(wl.weight * wl.reps) as total_volume
                FROM workout w
                LEFT JOIN workout_log wl ON w.id = wl.workout_id
                WHERE w.user_id = :user_id
                AND w.created_at >= :lookback_date
                GROUP BY w.id, w.title, w.phase, w.week, w.day_of_week, w.status, w.created_at
                ORDER BY w.created_at DESC
                LIMIT 10
            """)

            recent_result = db.execute(recent_workouts_sql, {
                "user_id": user_id,
                "lookback_date": lookback_date
            })

            recent_workouts = []
            for row in recent_result.fetchall():
                workout = {
                    "id": row.id,
                    "title": row.title,
                    "phase": row.phase,
                    "week": row.week,
                    "day": row.day_of_week,
                    "status": row.status,
                    "sets_logged": row.sets_logged or 0,
                    "volume": round(row.total_volume, 1) if row.total_volume else 0,
                    "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else None
                }
                recent_workouts.append(workout)

            summary["recent_workouts"] = {
                "count": len(recent_workouts),
                "workouts": recent_workouts,
                "days_back": days_back
            }

            # === LAST WORKOUT ===
            if recent_workouts:
                last_workout = recent_workouts[0]
                days_since = (today - datetime.fromisoformat(last_workout["date"]).date()).days
                summary["last_workout"] = {
                    "title": last_workout["title"],
                    "date": last_workout["date"],
                    "days_ago": days_since,
                    "sets_logged": last_workout["sets_logged"],
                    "volume": last_workout["volume"]
                }
            else:
                summary["last_workout"] = None

            # === UPCOMING WORKOUTS ===
            upcoming_sql = text("""
                SELECT
                    id,
                    name,
                    scheduled_days,
                    exercises,
                    created_at
                FROM fitness_template
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 5
            """)

            upcoming_result = db.execute(upcoming_sql, {"user_id": user_id})

            upcoming_workouts = []
            current_day = datetime.now().strftime('%A').lower()

            for row in upcoming_result.fetchall():
                scheduled_days = json.loads(row.scheduled_days) if isinstance(row.scheduled_days, str) else (row.scheduled_days or [])
                exercises = json.loads(row.exercises) if isinstance(row.exercises, str) else (row.exercises or [])

                is_today = current_day in [day.lower() for day in scheduled_days]

                workout = {
                    "id": row.id,
                    "name": row.name,
                    "scheduled_days": scheduled_days,
                    "exercise_count": len(exercises) if isinstance(exercises, list) else 0,
                    "is_scheduled_today": is_today
                }
                upcoming_workouts.append(workout)

            summary["upcoming_workouts"] = {
                "count": len(upcoming_workouts),
                "workouts": upcoming_workouts,
                "scheduled_today": [w for w in upcoming_workouts if w["is_scheduled_today"]]
            }

            # === RECOVERY METRICS ===
            # Check for recent recovery notes in fitness_note table
            recovery_sql = text("""
                SELECT content, note_type, created_at
                FROM fitness_note
                WHERE user_id = :user_id
                AND note_type IN ('recovery', 'soreness', 'energy')
                ORDER BY created_at DESC
                LIMIT 5
            """)

            recovery_result = db.execute(recovery_sql, {"user_id": user_id})

            recovery_notes = []
            for row in recovery_result.fetchall():
                recovery_notes.append({
                    "type": row.note_type,
                    "content": row.content,
                    "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else None
                })

            summary["recovery"] = {
                "recent_notes": recovery_notes,
                "count": len(recovery_notes)
            }

            # === WEEKLY STATS ===
            week_start = today - timedelta(days=today.weekday())  # Monday
            weekly_stats_sql = text("""
                SELECT
                    COUNT(DISTINCT w.id) as workouts_this_week,
                    COUNT(wl.id) as total_sets,
                    SUM(wl.weight * wl.reps) as total_volume
                FROM workout w
                LEFT JOIN workout_log wl ON w.id = wl.workout_id
                WHERE w.user_id = :user_id
                AND w.created_at >= :week_start
            """)

            weekly_result = db.execute(weekly_stats_sql, {
                "user_id": user_id,
                "week_start": week_start
            }).fetchone()

            summary["this_week"] = {
                "workouts": weekly_result.workouts_this_week or 0,
                "total_sets": weekly_result.total_sets or 0,
                "total_volume": round(weekly_result.total_volume, 1) if weekly_result.total_volume else 0
            }

            # Build response message
            msg_parts = []

            # Nutrition summary
            if summary["today_nutrition"]["meal_count"] > 0:
                nutr = summary["today_nutrition"]["totals"]
                msg_parts.append(
                    f"Today's nutrition: {summary['today_nutrition']['meal_count']} meals logged "
                    f"({nutr['calories']}cal, {nutr['protein']}g protein)"
                )
            else:
                msg_parts.append("No meals logged today yet")

            # Last workout
            if summary["last_workout"]:
                lw = summary["last_workout"]
                msg_parts.append(
                    f"Last workout: {lw['title']} ({lw['days_ago']} days ago, {lw['sets_logged']} sets)"
                )
            else:
                msg_parts.append(f"No workouts logged in the last {days_back} days")

            # This week
            msg_parts.append(
                f"This week: {summary['this_week']['workouts']} workouts, "
                f"{summary['this_week']['total_sets']} sets"
            )

            # Upcoming
            if summary["upcoming_workouts"]["scheduled_today"]:
                today_workout = summary["upcoming_workouts"]["scheduled_today"][0]
                msg_parts.append(f"Scheduled today: {today_workout['name']}")

            message = ". ".join(msg_parts) + "."

            return ToolResult(
                success=True,
                data=summary,
                message=message
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to get fitness summary: {str(e)}"
            )
        finally:
            db.close()
