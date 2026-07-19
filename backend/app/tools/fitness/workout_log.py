"""
Workout Log Tools
Tools for tracking workouts and exercises using existing workout system
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
from app.core.timezone import naive_local_now
import uuid
import json
import logging

logger = logging.getLogger(__name__)


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
                    current_day = naive_local_now().strftime('%A').lower()
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
                    "description": "ID of the workout being logged (optional - will auto-create today's workout if not provided)"
                },
                "exercise_id": {
                    "type": "string",
                    "description": "Exercise name or identifier"
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
                },
                "session_date": {
                    "type": "string",
                    "description": "Optional custom workout date in YYYY-MM-DD format (defaults to today)"
                },
                "session_time": {
                    "type": "string",
                    "description": "Optional full ISO timestamp for exact workout time"
                }
            },
            "required": ["exercise_id", "set_index"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Log a workout set"""
        exercise_id = kwargs.get("exercise_id")
        set_index = kwargs.get("set_index")
        weight = kwargs.get("weight")
        reps = kwargs.get("reps")
        rpe = kwargs.get("rpe")
        notes = kwargs.get("notes", "")
        session_date_str = kwargs.get("session_date")  # NEW: Optional custom date
        session_time_str = kwargs.get("session_time")  # NEW: Optional full timestamp

        db = get_fitness_db()

        try:
            # Use provided date or default to today
            if session_date_str:
                try:
                    today = datetime.fromisoformat(session_date_str.replace('Z', '+00:00')).date()
                except (ValueError, AttributeError):
                    today = datetime.now(timezone.utc).date()
            else:
                today = datetime.now(timezone.utc).date()

            workout_title = f"Workout - {today.strftime('%Y-%m-%d')}"

            # Check if workout already exists for today using session_date
            # This prevents race conditions when logging multiple sets
            check_today_sql = text("""
                SELECT id, title FROM workout
                WHERE user_id = :user_id
                AND title = :title
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = db.execute(check_today_sql, {"user_id": user_id, "title": workout_title})
            workout = result.fetchone()

            if not workout:
                # Create new workout for today
                workout_id = str(uuid.uuid4())
                create_workout_sql = text("""
                    INSERT INTO workout
                    (id, user_id, title, phase, week, day_of_week, status, prescription, created_at)
                    VALUES
                    (:id, :user_id, :title, 'Ad-hoc', 1, :day, 'completed', '{}', NOW())
                    RETURNING id, title
                """)
                # day_of_week column is INTEGER (0=Mon, 6=Sun)
                day_of_week_int = today.weekday()  # 0=Monday, 6=Sunday
                result = db.execute(create_workout_sql, {
                    "id": workout_id,
                    "user_id": user_id,
                    "title": workout_title,
                    "day": day_of_week_int
                })
                workout = result.fetchone()
                db.commit()
            else:
                workout_id = workout.id

            # Insert workout log entry
            log_id = str(uuid.uuid4())
            # Use the provided session_date and session_time
            # Parse session_time to datetime if provided, otherwise use noon
            if session_time_str:
                try:
                    from zoneinfo import ZoneInfo
                    # Parse as naive datetime (no timezone), then localize to Eastern
                    if 'Z' in session_time_str or '+' in session_time_str:
                        # Has timezone info, parse directly
                        session_time = datetime.fromisoformat(session_time_str.replace('Z', '+00:00'))
                    else:
                        # No timezone info - treat as Eastern time
                        naive_dt = datetime.fromisoformat(session_time_str)
                        eastern = ZoneInfo("America/New_York")
                        session_time = naive_dt.replace(tzinfo=eastern)
                    logger.info(f"✅ Parsed session_time: {session_time_str} → {session_time}")
                except (ValueError, AttributeError) as e:
                    # Default to noon if parsing fails
                    from zoneinfo import ZoneInfo
                    eastern = ZoneInfo("America/New_York")
                    session_time = datetime.combine(today, datetime.min.time().replace(hour=12)).replace(tzinfo=eastern)
                    logger.warning(f"⚠️  Failed to parse session_time '{session_time_str}': {e}, using noon default")
            else:
                # Default to noon on the session date in Eastern time
                from zoneinfo import ZoneInfo
                eastern = ZoneInfo("America/New_York")
                session_time = datetime.combine(today, datetime.min.time().replace(hour=12)).replace(tzinfo=eastern)
                logger.info(f"ℹ️  No session_time provided, using noon default: {session_time}")

            insert_sql = text("""
                INSERT INTO workout_log
                (id, workout_id, user_id, exercise_id, set_index, weight, reps, rpe, notes, session_date, session_time, created_at)
                VALUES
                (:id, :workout_id, :user_id, :exercise_id, :set_index, :weight, :reps, :rpe, :notes, :session_date, :session_time, NOW())
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
                "notes": notes,
                "session_date": today,  # Use the 'today' variable which respects session_date_str
                "session_time": session_time  # Save the actual workout time
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


class WorkoutDetailsTool(BaseTool):
    """Get detailed workout logs with all sets"""

    @property
    def name(self) -> str:
        return "workout_details"

    @property
    def description(self) -> str:
        return "Get detailed workout logs showing all logged sets (weight, reps, RPE) for a specific date or workout session. Use this to see what exercises were performed and how much weight was lifted."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to get workout details for (YYYY-MM-DD format). Defaults to today."
                },
                "workout_id": {
                    "type": "string",
                    "description": "Optional specific workout ID to get details for"
                },
                "exercise_name": {
                    "type": "string",
                    "description": "Optional filter by specific exercise name"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get detailed workout logs"""
        date_str = kwargs.get("date")
        workout_id = kwargs.get("workout_id")
        exercise_name = kwargs.get("exercise_name")

        db = get_fitness_db()

        try:
            # Default to today if no date provided
            if date_str:
                try:
                    target_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                except (ValueError, AttributeError):
                    target_date = datetime.now(timezone.utc).date()
            else:
                target_date = datetime.now(timezone.utc).date()

            # Build query based on filters
            filters = ["wl.user_id = :user_id"]
            params = {"user_id": user_id}

            if workout_id:
                filters.append("wl.workout_id = :workout_id")
                params["workout_id"] = workout_id
            else:
                # Filter by date if no specific workout_id
                filters.append("wl.session_date = :session_date")
                params["session_date"] = target_date

            if exercise_name:
                filters.append("wl.exercise_id ILIKE :exercise_name")
                params["exercise_name"] = f"%{exercise_name}%"

            filter_clause = " AND ".join(filters)

            # Query workout_log with workout details
            query_sql = text(f"""
                SELECT
                    wl.id as log_id,
                    wl.workout_id,
                    wl.exercise_id,
                    wl.set_index,
                    wl.weight,
                    wl.reps,
                    wl.rpe,
                    wl.notes,
                    wl.session_date,
                    wl.created_at,
                    w.title as workout_title,
                    w.phase,
                    w.status
                FROM workout_log wl
                LEFT JOIN workout w ON wl.workout_id = w.id
                WHERE {filter_clause}
                ORDER BY wl.exercise_id, wl.set_index
            """)

            result = db.execute(query_sql, params)
            rows = result.fetchall()

            if not rows:
                return ToolResult(
                    success=True,
                    data={"exercises": [], "total_sets": 0, "date": target_date.isoformat()},
                    message=f"No workout logs found for {target_date}"
                )

            # Group sets by exercise
            exercises = {}
            workout_title = None
            workout_phase = None

            for row in rows:
                if workout_title is None:
                    workout_title = row.workout_title
                    workout_phase = row.phase

                exercise_id = row.exercise_id
                if exercise_id not in exercises:
                    exercises[exercise_id] = {
                        "exercise_name": exercise_id,
                        "sets": []
                    }

                exercises[exercise_id]["sets"].append({
                    "set_index": row.set_index,
                    "weight": row.weight,
                    "reps": row.reps,
                    "rpe": row.rpe,
                    "notes": row.notes
                })

            exercise_list = list(exercises.values())

            return ToolResult(
                success=True,
                data={
                    "date": target_date.isoformat(),
                    "workout_title": workout_title,
                    "workout_phase": workout_phase,
                    "exercises": exercise_list,
                    "total_sets": len(rows),
                    "total_exercises": len(exercises)
                },
                message=f"Found {len(exercises)} exercise(s) with {len(rows)} total set(s) for {target_date}"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to get workout details: {str(e)}"
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
