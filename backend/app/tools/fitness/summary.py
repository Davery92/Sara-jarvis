"""
Fitness Summary Tool
Provides on-demand fitness status for regular Sara chat
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
from app.core.timezone import naive_local_now, naive_utc_now
import json


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


def _session_volume(day_sets) -> float:
    """Tonnage for one session, from effective loads only.

    A set whose effective load is unknown is left out rather than counted at
    its recorded number: a dumbbell press logged as 40 is 80 moved, and an
    assisted pull-up logged as 30 is 30 of *help*. Counting either as written
    makes the volume wrong in a direction a reader cannot see.
    """
    total = 0.0
    for item in day_sets:
        load = item.get("effective_load")
        reps = item.get("reps")
        if load is None or not reps:
            continue
        total += float(load) * int(reps)
    return round(total, 1)


def _session_title(db, user_id: str, row) -> str:
    """The session's template name, or a plain date label."""
    if row.get("template_id"):
        try:
            name = db.execute(text("""
                SELECT name FROM fitness_template
                WHERE id = :id AND user_id = :uid
            """), {"id": row["template_id"], "uid": user_id}).scalar()
            if name:
                return name
        except Exception:
            pass
    return f"Session {row.get('date') or ''}".strip()


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

        try:
            from app.services.fitness.consumers import (
                athlete_local_today, nutrition_day, training_window,
            )

            # The athlete's today, not the server's UTC date. This used to be
            # `datetime.now(timezone.utc).date()`, so from 20:00 ET onward it
            # asked for tomorrow and "today's nutrition" came back empty every
            # evening — the hours David is most likely to ask.
            today = athlete_local_today(db, user_id)
            lookback_date = today - timedelta(days=days_back)

            summary = {}

            # === TODAY'S NUTRITION ===
            # Delegated to the one implementation (Step 18). It resolves the
            # day from `logged_at` (naive ET wall-clock), not `created_at`
            # (naive UTC insert time): those are different days for every meal
            # logged before 20:00 ET and for every meal entered after the fact,
            # so this tool and the chat context used to report two different
            # totals in the same turn.
            day = nutrition_day(db, user_id, today)
            meals = [
                {
                    "meal_type": meal["meal_type"],
                    "food": meal["food"],
                    "calories": meal["calories"] or 0,
                    "protein": meal["protein"] or 0,
                    "carbs": meal["carbs"] or 0,
                    "fats": meal["fats"] or 0,
                    "time": meal["time"],
                }
                for meal in day["meals"]
            ]
            summary["today_nutrition"] = {
                "meals": meals,
                "totals": {
                    "calories": round(day["eaten"]["calories"], 1),
                    "protein": round(day["eaten"]["protein"], 1),
                    "carbs": round(day["eaten"]["carbs"], 1),
                    "fats": round(day["eaten"]["fat"], 1),
                },
                # Which macros were actually recorded, so a reader can tell an
                # unlogged macro from a zero one.
                "known_fields": day["known_fields"],
                "targets": day["target"],
                "target_provenance": day["target_provenance"],
                "day_type": day["day_type"],
                "meal_count": day["meal_count"],
            }

            # === RECENT WORKOUTS ===
            # Delegated to `training_window`, which de-duplicates the three
            # tables that can each describe one training bout (`workout`,
            # `workout_session`, `active_workout_session`) and dates a session
            # by `session_date` rather than by the `workout` row's `created_at`
            # — a program importer writes a whole block's rows in one
            # transaction, so `created_at` ordering between them is arbitrary.
            window = training_window(db, user_id, lookback_date, today + timedelta(days=1))

            recent_workouts = []
            for row in window["session_rows"][:10]:
                day_sets = window["by_date"].get(row["date"] or "", [])
                recent_workouts.append({
                    "id": row["key"],
                    "title": _session_title(db, user_id, row),
                    "phase": None,
                    "week": None,
                    "day": (
                        datetime.fromisoformat(row["date"]).strftime("%A").lower()
                        if row["date"] else None
                    ),
                    "status": row["status"],
                    "sets_logged": len(day_sets) or row["sets_completed"] or 0,
                    # The volume for this session only, from effective loads.
                    # `SUM(weight * reps)` over the integer column dropped
                    # fractional plates, counted one dumbbell, and counted an
                    # assisted pull-up's assistance as work.
                    "volume": _session_volume(day_sets),
                    "date": row["date"],
                })

            summary["recent_workouts"] = {
                "count": len(recent_workouts),
                "workouts": recent_workouts,
                "days_back": days_back,
            }

            # === LAST WORKOUT ===
            dated = [w for w in recent_workouts if w["date"]]
            if dated:
                last_workout = max(dated, key=lambda w: w["date"])
                days_since = (today - datetime.fromisoformat(last_workout["date"]).date()).days
                summary["last_workout"] = {
                    "title": last_workout["title"],
                    "date": last_workout["date"],
                    "days_ago": days_since,
                    "sets_logged": last_workout["sets_logged"],
                    "volume": last_workout["volume"],
                }
            else:
                summary["last_workout"] = None

            # === UPCOMING WORKOUTS ===
            # Scoped to the phase in effect, ordered the way the plan runs.
            # This used to take the 5 most recent templates by `created_at`
            # across every phase of every program — an importer writes a whole
            # program's templates in one transaction, so that ordering is
            # arbitrary between them and "scheduled today" was a coin flip.
            from app.services.phase_resolution import get_effective_phase
            today_date = naive_local_now().date()
            effective_phase = get_effective_phase(db, user_id, today_date)

            upcoming_sql = text("""
                SELECT
                    id,
                    name,
                    scheduled_days,
                    exercises,
                    created_at
                FROM fitness_template
                WHERE user_id = :user_id
                  AND (
                    (CAST(:phase_id AS VARCHAR) IS NOT NULL AND phase_id = CAST(:phase_id AS VARCHAR))
                    OR (CAST(:phase_id AS VARCHAR) IS NULL AND phase_id IS NULL)
                  )
                ORDER BY order_in_phase ASC NULLS LAST, created_at DESC
            """)

            upcoming_result = db.execute(upcoming_sql, {
                "user_id": user_id,
                "phase_id": effective_phase["id"] if effective_phase else None,
            })

            upcoming_workouts = []
            current_day = naive_local_now().strftime('%A').lower()

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
            # Recent recovery notes from fitness_note.
            #
            # Two fixes here (D11). The column is `category`, not `note_type` —
            # this query raised UndefinedColumn on every call, aborting the
            # whole fitness_summary tool before it ever returned. And it had no
            # date bound, so once it did run, the five most recent notes came
            # back however old they were and a soreness note from March would
            # read as current state in an August summary.
            #
            # fitness_note.created_at is a naive column written with NOW() on a
            # UTC session, so the bound is naive UTC.
            recovery_sql = text("""
                SELECT content, category, created_at
                FROM fitness_note
                WHERE user_id = :user_id
                AND category IN ('recovery', 'soreness', 'energy')
                AND created_at >= :since
                ORDER BY created_at DESC
                LIMIT 5
            """)

            recovery_result = db.execute(recovery_sql, {
                "user_id": user_id,
                "since": naive_utc_now() - timedelta(days=14),
            })

            recovery_notes = []
            for row in recovery_result.fetchall():
                recovery_notes.append({
                    "type": row.category,
                    "content": row.content,
                    "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else None
                })

            summary["recovery"] = {
                "recent_notes": recovery_notes,
                "count": len(recovery_notes),
                "window_days": 14,
                "note": (
                    "No recovery notes logged in the last 14 days"
                    if not recovery_notes else None
                ),
            }

            # === WEEKLY STATS ===
            # Monday of the athlete's current local week, through today
            # inclusive. The old query bounded on `workout.created_at >=
            # week_start` with a UTC `today`, so on Monday it could report
            # Sunday's session and on Sunday evening it reported none.
            week_start = today - timedelta(days=today.weekday())
            week = training_window(db, user_id, week_start, today + timedelta(days=1))

            summary["this_week"] = {
                "workouts": week["sessions"],
                "total_sets": week["sets"],
                "total_volume": week["tonnage"] or 0,
                "volume_unit": week["tonnage_unit"],
                # A tonnage with excluded sets is a floor, not a total, and
                # saying so is the difference between a number and a claim.
                "sets_excluded_from_volume": week["sets_excluded_from_tonnage"],
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

            # Upcoming — name every session, in order. A two-a-day has two.
            scheduled_today = summary["upcoming_workouts"]["scheduled_today"]
            if scheduled_today:
                msg_parts.append("Scheduled today: "
                                 + " · ".join(w["name"] for w in scheduled_today))

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
