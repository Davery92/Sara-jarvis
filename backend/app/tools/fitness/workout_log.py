"""
Workout Log Tools
Tools for tracking workouts and exercises using existing workout system
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
import uuid
import json


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class WorkoutListTool(BaseTool):
    """List available workouts and workout plans"""

    @property
    def name(self) -> str:
        return "workout_list"

    @property
    def description(self) -> str:
        return "List available workouts, optionally filtered by status (scheduled, completed, all). Shows planned workouts from fitness plans."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by workout status",
                    "enum": ["scheduled", "completed", "all"],
                    "default": "all"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List workouts"""
        status = kwargs.get("status", "all")
        limit = kwargs.get("limit", 20)

        db = get_fitness_db()

        try:
            status_filter = ""
            params = {"user_id": user_id, "limit": limit}

            if status != "all":
                status_filter = "AND w.status = :status"
                params["status"] = status

            sql = text(f"""
                SELECT w.id, w.title, w.phase, w.week, w.day_of_week,
                       w.duration_min, w.status, w.prescription, w.created_at,
                       NULL as plan_title
                FROM workout w
                WHERE w.user_id = :user_id {status_filter}
                ORDER BY w.created_at DESC
                LIMIT :limit
            """)

            result = db.execute(sql, params)

            workouts = []
            for row in result.fetchall():
                prescription = json.loads(row.prescription) if isinstance(row.prescription, str) else (row.prescription or {})

                workout = {
                    "workout_id": row.id,
                    "title": row.title,
                    "plan": row.plan_title,
                    "phase": row.phase,
                    "week": row.week,
                    "day": row.day_of_week,
                    "duration_min": row.duration_min,
                    "status": row.status,
                    "exercises": prescription.get("exercises", []),
                    "created_at": row.created_at.isoformat() if row.created_at else None
                }
                workouts.append(workout)

            # Fallback: If no workouts found, query fitness_template table
            if not workouts:
                template_sql = text("""
                    SELECT id, name, scheduled_days, exercises, created_at
                    FROM fitness_template
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)

                template_result = db.execute(template_sql, {"user_id": user_id, "limit": limit})

                for row in template_result.fetchall():
                    exercises = json.loads(row.exercises) if isinstance(row.exercises, str) else (row.exercises or [])
                    scheduled_days = json.loads(row.scheduled_days) if isinstance(row.scheduled_days, str) else (row.scheduled_days or [])

                    # Get current day of week to mark if it's scheduled for today
                    from datetime import datetime
                    current_day = datetime.now().strftime('%A').lower()
                    is_today = current_day in [day.lower() for day in scheduled_days]

                    workout = {
                        "workout_id": row.id,
                        "title": row.name,
                        "plan": "Workout Template",
                        "phase": None,
                        "week": None,
                        "day": ", ".join(scheduled_days) if scheduled_days else "Not scheduled",
                        "duration_min": None,
                        "status": "scheduled" if is_today else "template",
                        "exercises": exercises if isinstance(exercises, list) else [],
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "is_template": True
                    }
                    workouts.append(workout)

            return ToolResult(
                success=True,
                data={
                    "workouts": workouts,
                    "total": len(workouts),
                    "status_filter": status
                },
                message=f"Found {len(workouts)} workout(s)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list workouts: {str(e)}"
            )
        finally:
            db.close()


class WorkoutLogCreateTool(BaseTool):
    """Log exercise sets for a workout"""

    @property
    def name(self) -> str:
        return "workout_log_create"

    @property
    def description(self) -> str:
        return "Log exercise sets completed during a workout. Records weight, reps, RPE (Rate of Perceived Exertion 1-10) for each set."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "ID of the workout being logged"
                },
                "exercise_id": {
                    "type": "string",
                    "description": "Exercise identifier (optional)"
                },
                "set_index": {
                    "type": "integer",
                    "description": "Set number (1, 2, 3...)"
                },
                "weight": {
                    "type": "integer",
                    "description": "Weight used (lbs or kg)"
                },
                "reps": {
                    "type": "integer",
                    "description": "Repetitions completed"
                },
                "rpe": {
                    "type": "integer",
                    "description": "Rate of Perceived Exertion (1-10)"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes about the set"
                }
            },
            "required": ["workout_id", "set_index"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Log a workout set"""
        workout_id = kwargs.get("workout_id")
        exercise_id = kwargs.get("exercise_id")
        set_index = kwargs.get("set_index")
        weight = kwargs.get("weight")
        reps = kwargs.get("reps")
        rpe = kwargs.get("rpe")
        notes = kwargs.get("notes", "")

        db = get_fitness_db()

        try:
            # Verify workout belongs to user
            check_sql = text("""
                SELECT id, title FROM workout
                WHERE id = :workout_id AND user_id = :user_id
            """)
            result = db.execute(check_sql, {"workout_id": workout_id, "user_id": user_id})
            workout = result.fetchone()

            if not workout:
                return ToolResult(
                    success=False,
                    message="Workout not found or doesn't belong to user"
                )

            # Insert workout log entry
            log_id = str(uuid.uuid4())
            insert_sql = text("""
                INSERT INTO workout_log
                (id, workout_id, user_id, exercise_id, set_index, weight, reps, rpe, notes, created_at)
                VALUES
                (:id, :workout_id, :user_id, :exercise_id, :set_index, :weight, :reps, :rpe, :notes, NOW())
                RETURNING id, created_at
            """)

            result = db.execute(insert_sql, {
                "id": log_id,
                "workout_id": workout_id,
                "user_id": user_id,
                "exercise_id": exercise_id,
                "set_index": set_index,
                "weight": weight,
                "reps": reps,
                "rpe": rpe,
                "notes": notes
            })
            db.commit()

            row = result.fetchone()

            return ToolResult(
                success=True,
                data={
                    "log_id": log_id,
                    "workout_id": workout_id,
                    "workout_title": workout.title,
                    "set_index": set_index,
                    "weight": weight,
                    "reps": reps,
                    "rpe": rpe,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                },
                message=f"Logged set {set_index} for {workout.title}: {weight}lbs x {reps} reps @ RPE {rpe}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to log workout set: {str(e)}"
            )
        finally:
            db.close()


class WorkoutStatsTool(BaseTool):
    """Get workout statistics and progress"""

    @property
    def name(self) -> str:
        return "workout_stats"

    @property
    def description(self) -> str:
        return "Get workout statistics for a date range: total workouts, exercises logged, volume trends."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date (ISO format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (ISO format)"
                },
                "period": {
                    "type": "string",
                    "description": "Stats period",
                    "enum": ["week", "month", "all"],
                    "default": "week"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get workout statistics"""
        period = kwargs.get("period", "week")
        start_date_str = kwargs.get("start_date")
        end_date_str = kwargs.get("end_date")

        # Default to last week
        today = datetime.now(timezone.utc).date()
        if period == "month":
            start_date = today - timedelta(days=30)
            end_date = today
        elif period == "all":
            start_date = today - timedelta(days=365)
            end_date = today
        else:  # week
            start_date = today - timedelta(days=7)
            end_date = today

        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).date()
            except:
                pass

        db = get_fitness_db()

        try:
            # Get workout log statistics
            stats_sql = text("""
                SELECT
                    COUNT(DISTINCT wl.workout_id) as total_workouts,
                    COUNT(*) as total_sets,
                    SUM(wl.weight * wl.reps) as total_volume,
                    AVG(wl.rpe) as avg_rpe
                FROM workout_log wl
                WHERE wl.user_id = :user_id
                AND wl.created_at >= :start_date
                AND wl.created_at < :end_date
            """)

            result = db.execute(stats_sql, {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date + timedelta(days=1)
            })

            row = result.fetchone()

            # Get completed workouts
            workouts_sql = text("""
                SELECT DISTINCT w.id, w.title, w.status,
                       COUNT(wl.id) as sets_logged
                FROM workout w
                LEFT JOIN workout_log wl ON w.id = wl.workout_id
                WHERE w.user_id = :user_id
                AND w.created_at >= :start_date
                AND w.created_at < :end_date
                GROUP BY w.id, w.title, w.status
                ORDER BY w.created_at DESC
            """)

            workouts_result = db.execute(workouts_sql, {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date + timedelta(days=1)
            })

            workouts = []
            for w in workouts_result.fetchall():
                workouts.append({
                    "workout_id": w.id,
                    "title": w.title,
                    "status": w.status,
                    "sets_logged": w.sets_logged
                })

            stats = {
                "period": period,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "summary": {
                    "total_workouts": row.total_workouts or 0,
                    "total_sets": row.total_sets or 0,
                    "total_volume": round(row.total_volume, 1) if row.total_volume else 0,
                    "avg_rpe": round(row.avg_rpe, 1) if row.avg_rpe else 0
                },
                "workouts": workouts
            }

            return ToolResult(
                success=True,
                data=stats,
                message=f"Workout stats for {start_date} to {end_date}: {row.total_workouts or 0} workouts, {row.total_sets or 0} sets"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to get workout stats: {str(e)}"
            )
        finally:
            db.close()
