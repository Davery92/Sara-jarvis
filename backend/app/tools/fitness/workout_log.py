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

            # Fallback: if there are no real workouts, show the *templates* —
            # but kept in their own key, never mixed into `workouts`. Merged in,
            # a template is indistinguishable from a session that happened, and
            # a plan David never executed comes back as a workout he did (D8).
            templates = []
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

                    templates.append({
                        "template_id": row.id,
                        "title": row.name,
                        "source": "template",
                        "scheduled_days": scheduled_days,
                        "scheduled_today": is_today,
                        "exercises": exercises if isinstance(exercises, list) else [],
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    })

            if workouts:
                message = f"Found {len(workouts)} workout(s)"
            elif templates:
                message = (
                    f"No workouts found. Showing {len(templates)} saved workout TEMPLATE(s) instead — "
                    "these are plans, not sessions David performed. Do not describe them as completed "
                    "or scheduled workouts."
                )
            else:
                message = "No workouts and no workout templates found."

            return ToolResult(
                success=True,
                data={
                    "workouts": workouts,
                    "total": len(workouts),
                    "templates": templates,
                    "status_filter": status
                },
                message=message
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
                  AND wl.voided_at IS NULL
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

        db = get_fitness_db()

        # Default to last week, on the athlete's calendar. A UTC `today` is
        # tomorrow from 20:00 ET onward, so "this week" silently included a
        # day that had not happened and excluded the one just trained.
        from app.services.fitness.consumers import athlete_local_today
        today = athlete_local_today(db, user_id)
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

        try:
            # Step 18: delegated to the one implementation, so this tool, the
            # weekly health report and the Coach API report the same numbers
            # for the same week. Three things change:
            #
            # * sessions are de-duplicated across `workout`,
            #   `workout_session` and `active_workout_session` rather than
            #   counted as distinct `workout_id`s — all three can describe the
            #   same bout;
            # * sets are dated by `session_date`, not by `created_at`, which
            #   is naive UTC insert time and put a late-evening session on the
            #   next day;
            # * volume uses the effective load, so fractional plates survive,
            #   a dumbbell counts both hands, and assisted work is excluded
            #   instead of counting the assistance as load.
            from app.services.fitness.consumers import training_window

            window = training_window(db, user_id, start_date, end_date + timedelta(days=1))

            workouts = []
            for row in window["session_rows"]:
                day_sets = window["by_date"].get(row["date"] or "", [])
                workouts.append({
                    "workout_id": row["key"],
                    "title": row["date"] or "session",
                    "status": row["status"],
                    "sets_logged": len(day_sets) or row["sets_completed"] or 0,
                })

            stats = {
                "period": period,
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "summary": {
                    # COUNT is always a real number; SUM/AVG come back NULL when
                    # nothing matched. `or 0` collapsed that into "avg RPE 0",
                    # which reads as a logged effort of zero rather than as no
                    # logged effort at all (D10) — so nulls stay null.
                    "total_workouts": window["sessions"],
                    "total_sets": window["sets"],
                    "working_sets": window["working_sets"],
                    "total_volume": window["tonnage"],
                    "total_volume_unit": window["tonnage_unit"],
                    # Named, so the volume reads as a floor rather than a
                    # total when some sets could not be counted.
                    "sets_excluded_from_volume": window["sets_excluded_from_tonnage"],
                    "avg_rpe": window["avg_rpe"],
                },
                "workouts": workouts
            }

            if not stats["summary"]["total_sets"]:
                message = (
                    f"No sets logged between {start_date} and {end_date}. "
                    "Volume and RPE are null because nothing was recorded — not because they were zero."
                )
            else:
                rpe = stats["summary"]["avg_rpe"]
                message = (
                    f"Workout stats for {start_date} to {end_date}: "
                    f"{stats['summary']['total_workouts']} workouts, {stats['summary']['total_sets']} sets, "
                    f"avg RPE {rpe if rpe is not None else 'not recorded'}"
                )

            return ToolResult(
                success=True,
                data=stats,
                message=message
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to get workout stats: {str(e)}"
            )
        finally:
            db.close()


class WorkoutLogCorrectTool(BaseTool):
    """Correct a workout set David has already logged.

    Reliable-assistant plan Phase C4: *"Expose coherent operations such as…
    correct food quantity, correct workout set… Do not require the model to
    improvise coupled delete/create sequences."* Food, notes, lists, reminders
    and timers each got their correction operation; the workout set was the one
    left on the list, and its absence has the same consequence as the food one
    did (finding 35): with no way to fix the wrong row, the only thing available
    is to log a corrected copy, and then BOTH are in the set history — which is
    the input to `progressive_overload.py`, so a phantom set does not just read
    wrong, it prescribes wrong.

    "225 for 5, not 3" and "that was 235 not 225" are the whole case. It updates
    one row in place, keyed by the row's own id and owner, and reads the row back
    afterwards so what David is told is what the table holds.
    """

    @property
    def name(self) -> str:
        return "workout_log_correct"

    @property
    def description(self) -> str:
        return (
            "Fix a set David has already logged — '225 for 5, not 3', 'that was 235 "
            "not 225', 'that one was an 8 not a 6'. Changes the existing set: use this "
            "rather than logging a corrected copy, which leaves the wrong set in his "
            "history and in the progression math. Find the set first with "
            "workout_details and pass its real log_id."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_id": {
                    "type": "string",
                    "description": "The set to fix (from workout_details).",
                },
                "weight": {"type": "number", "description": "Corrected weight in lbs."},
                "reps": {"type": "integer", "description": "Corrected rep count."},
                "rpe": {"type": "integer", "description": "Corrected RPE, 1-10."},
                "notes": {"type": "string", "description": "Corrected note on the set."},
            },
            "required": ["log_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        log_id = kwargs.get("log_id")
        if not log_id:
            return ToolResult(success=False, message="log_id is required.")

        fields = {
            name: kwargs.get(name)
            for name in ("weight", "reps", "rpe", "notes")
            if kwargs.get(name) is not None
        }
        if not fields:
            return ToolResult(
                success=False,
                message="Nothing to correct — say what changed (weight, reps, RPE or the note).",
            )

        if "rpe" in fields:
            try:
                rpe = int(fields["rpe"])
            except (TypeError, ValueError):
                return ToolResult(success=False, message="RPE must be a whole number 1-10.")
            if not 1 <= rpe <= 10:
                return ToolResult(success=False, message="RPE only goes 1 to 10.")
            fields["rpe"] = rpe
        for numeric in ("weight", "reps"):
            if numeric in fields:
                try:
                    value = float(fields[numeric])
                except (TypeError, ValueError):
                    return ToolResult(success=False, message=f"{numeric} must be a number.")
                if value <= 0:
                    return ToolResult(
                        success=False,
                        message=f"{numeric} must be greater than zero — to remove a set, say so.",
                    )
                fields[numeric] = int(value) if numeric == "reps" else value

        db = get_fitness_db()
        try:
            # Owner-scoped read first, so "that set isn't yours" and "that set
            # doesn't exist" cannot be answered with each other's message.
            row = db.execute(text("""
                SELECT id, set_index, weight, reps, rpe, notes, session_date
                FROM workout_log WHERE id = :id AND user_id = :uid
            """), {"id": log_id, "uid": user_id}).mappings().first()
            if not row:
                return ToolResult(
                    success=False,
                    message="That set isn't there — nothing was changed.",
                )

            before = {
                "set_index": row["set_index"], "weight": row["weight"],
                "reps": row["reps"], "rpe": row["rpe"],
            }
            changed = [
                f"{name} ({row[name]} → {value})"
                for name, value in fields.items()
                if name != "notes" and row[name] != value
            ]
            if fields.get("notes") is not None and fields["notes"] != (row["notes"] or ""):
                changed.append("note")
            if not changed:
                return ToolResult(
                    success=False,
                    message="That set already reads that way — nothing changed.",
                )

            assignments = ", ".join(f"{name} = :{name}" for name in fields)
            params = dict(fields)
            params.update({"id": log_id, "uid": user_id})
            result = db.execute(text(
                f"UPDATE workout_log SET {assignments} WHERE id = :id AND user_id = :uid"
            ), params)
            if not result.rowcount:
                db.rollback()
                return ToolResult(
                    success=False,
                    message="That set isn't there any more — nothing was changed.",
                )
            db.commit()

            # Read the row back. The tool's own account of what it wrote is not
            # evidence about what the table holds.
            after = db.execute(text(
                "SELECT set_index, weight, reps, rpe, notes FROM workout_log "
                "WHERE id = :id AND user_id = :uid"
            ), {"id": log_id, "uid": user_id}).mappings().first()

            summary = (
                f"Fixed set {after['set_index']}: {', '.join(changed)}. "
                f"It now reads {after['weight']:g}lbs x {after['reps']} reps"
            )
            summary += f" @ RPE {after['rpe']}." if after["rpe"] is not None else "."
            summary += " Still one set, not a second one."

            return ToolResult(
                success=True,
                data={
                    "log_id": log_id,
                    "changed": changed,
                    "before": before,
                    "after": {
                        "set_index": after["set_index"],
                        "weight": after["weight"],
                        "reps": after["reps"],
                        "rpe": after["rpe"],
                        "notes": after["notes"],
                    },
                },
                message=summary,
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to correct the set: {e}")
        finally:
            db.close()
