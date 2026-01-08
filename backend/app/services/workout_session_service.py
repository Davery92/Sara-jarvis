"""
Workout Session Service

Manages active workout sessions for real-time workout tracking and Sara's coaching context.
Provides session CRUD, set logging, progress tracking, and context generation for chat.
"""

import json
import logging
import os
import uuid
import httpx
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from typing import Optional, Dict, List, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Local LLM for workout coaching - use gpt-oss:120b on local endpoint
WORKOUT_LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
WORKOUT_LLM_MODEL = "gpt-oss:120b"


class WorkoutSessionService:
    """Manages active workout sessions for real-time coaching"""

    async def start_workout(
        self,
        user_id: str,
        template_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Start a new workout session from a template.

        1. End any existing active session
        2. Fetch template and calculate weight suggestions
        3. Create session with workout snapshot

        Returns the created session with full workout data.
        """
        try:
            # 1. End any existing active session
            db.execute(text("""
                UPDATE active_workout_session
                SET status = 'abandoned', completed_at = NOW(), updated_at = NOW()
                WHERE user_id = :user_id AND status = 'active'
            """), {"user_id": user_id})

            # 2. Fetch template
            template_row = db.execute(text("""
                SELECT id, name, phase_id, scheduled_days, exercises, notes
                FROM fitness_template
                WHERE id = :template_id AND user_id = :user_id
            """), {"template_id": template_id, "user_id": user_id}).fetchone()

            if not template_row:
                raise ValueError(f"Template {template_id} not found")

            template = dict(template_row._mapping)
            exercises = json.loads(template.get("exercises", "[]"))

            # 3. Calculate weight suggestions for each exercise (reuse workout_suggest logic)
            exercise_snapshots = []
            for exercise_spec in exercises:
                exercise_name = exercise_spec.get("name")
                target_sets = exercise_spec.get("sets", 3)
                target_reps = exercise_spec.get("reps", "8-10")
                target_rpe = exercise_spec.get("rpe_target", 7)
                rest_seconds = exercise_spec.get("rest_seconds", 120)

                # Get last session data for this exercise
                past_logs = db.execute(text("""
                    SELECT session_date, weight, reps, rpe, notes
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND LOWER(exercise_id) = LOWER(:exercise_name)
                      AND session_date IS NOT NULL
                    ORDER BY session_date DESC, created_at DESC
                    LIMIT 15
                """), {"user_id": user_id, "exercise_name": exercise_name}).fetchall()

                # Group by session date
                sessions_by_date = {}
                for log in past_logs:
                    log_date = log.session_date
                    if log_date not in sessions_by_date:
                        sessions_by_date[log_date] = []
                    sessions_by_date[log_date].append({
                        "weight": float(log.weight) if log.weight else 0,
                        "reps": log.reps,
                        "rpe": log.rpe or 7
                    })

                # Calculate suggestion based on last session
                last_session_data = None
                suggested_weight = None
                progression_note = ""

                if sessions_by_date:
                    last_date = max(sessions_by_date.keys())
                    last_sets = sessions_by_date[last_date]
                    last_session_data = {
                        "date": str(last_date),
                        "weights": [s["weight"] for s in last_sets],
                        "reps": [s["reps"] for s in last_sets],
                        "avg_rpe": sum(s["rpe"] for s in last_sets) / len(last_sets)
                    }

                    avg_weight = sum(last_session_data["weights"]) / len(last_session_data["weights"])
                    avg_rpe = last_session_data["avg_rpe"]
                    min_reps = min(last_session_data["reps"]) if last_session_data["reps"] else 0

                    # Parse target rep range
                    if "-" in str(target_reps):
                        min_target_reps = int(target_reps.split("-")[0])
                    else:
                        min_target_reps = int(target_reps)

                    # Progressive overload logic
                    is_lower_body = any(kw in exercise_name.lower() for kw in ["squat", "deadlift", "leg", "lunge", "hip"])
                    weight_increment = 10 if is_lower_body else 5

                    if avg_rpe < 7.5 and min_reps >= min_target_reps:
                        suggested_weight = avg_weight + weight_increment
                        progression_note = f"Last session felt easy (RPE {avg_rpe:.1f}). Adding {weight_increment}lbs."
                    elif avg_rpe >= 8.5:
                        suggested_weight = avg_weight
                        progression_note = f"Last session was tough (RPE {avg_rpe:.1f}). Maintaining weight."
                    elif min_reps < min_target_reps:
                        suggested_weight = avg_weight
                        progression_note = f"Focus on hitting full reps at {avg_weight}lbs."
                    else:
                        suggested_weight = avg_weight + 2.5
                        progression_note = f"Solid progression from {avg_weight}lbs."
                else:
                    progression_note = "First time - start conservative at RPE 7."

                exercise_snapshots.append({
                    "name": exercise_name,
                    "sets": target_sets,
                    "reps": target_reps,
                    "rpe_target": target_rpe,
                    "rest_seconds": rest_seconds,
                    "suggested_weight": suggested_weight,
                    "progression_note": progression_note,
                    "last_session": last_session_data
                })

            # 4. Create workout snapshot
            workout_snapshot = {
                "template_id": template_id,
                "template_name": template["name"],
                "template_notes": template.get("notes"),
                "exercises": exercise_snapshots,
                "total_sets": sum(e["sets"] for e in exercise_snapshots)
            }

            # 5. Insert into workout table (for workout_log foreign key)
            session_id = str(uuid.uuid4())
            logger.info(f"[WorkoutSession] Inserting new session: id={session_id}, user_id={user_id}, template_id={template_id}")

            # Create workout entry for foreign key reference
            db.execute(text("""
                INSERT INTO workout (id, user_id, title, status)
                VALUES (:id, :user_id, :title, 'in_progress')
            """), {
                "id": session_id,
                "user_id": user_id,
                "title": template["name"]
            })

            # Insert active session
            result = db.execute(text("""
                INSERT INTO active_workout_session (
                    id, user_id, template_id, status, workout_snapshot
                ) VALUES (
                    :id, :user_id, :template_id, 'active', :workout_snapshot
                )
                RETURNING id, started_at
            """), {
                "id": session_id,
                "user_id": user_id,
                "template_id": template_id,
                "workout_snapshot": json.dumps(workout_snapshot)
            })
            row = result.fetchone()
            logger.info(f"[WorkoutSession] INSERT returned: id={row.id}, started_at={row.started_at}")
            db.commit()
            logger.info(f"[WorkoutSession] Commit successful for session {row.id}")

            return {
                "id": row.id,
                "status": "active",
                "started_at": row.started_at.isoformat(),
                "template_name": template["name"],
                "workout_snapshot": workout_snapshot,
                "current_exercise_index": 0,
                "current_set_index": 0,
                "total_sets_completed": 0
            }

        except Exception as e:
            db.rollback()
            logger.exception(f"Failed to start workout: {e}")
            raise

    async def get_active_session(
        self,
        user_id: str,
        db: Session
    ) -> Optional[Dict[str, Any]]:
        """Get the user's current active workout session if any."""
        try:
            logger.info(f"[WorkoutSession] get_active_session for user_id: {user_id}")
            row = db.execute(text("""
                SELECT
                    id, user_id, template_id, status, started_at, completed_at,
                    current_exercise_index, current_set_index, workout_snapshot,
                    rest_timer_started_at, rest_timer_duration_seconds,
                    total_sets_completed, total_volume, notes, updated_at
                FROM active_workout_session
                WHERE user_id = :user_id AND status = 'active'
                LIMIT 1
            """), {"user_id": user_id}).fetchone()

            if not row:
                # Debug: check if there are ANY sessions for this user
                all_sessions = db.execute(text("""
                    SELECT id, status, started_at FROM active_workout_session
                    WHERE user_id = :user_id ORDER BY started_at DESC LIMIT 5
                """), {"user_id": user_id}).fetchall()
                logger.info(f"[WorkoutSession] No active session found. All sessions for user: {[dict(r._mapping) for r in all_sessions]}")
                return None

            session = dict(row._mapping)
            # JSONB columns are returned as dicts by SQLAlchemy, no need to parse
            snapshot = session["workout_snapshot"]
            if isinstance(snapshot, str):
                session["workout_snapshot"] = json.loads(snapshot) if snapshot else {}
            elif snapshot is None:
                session["workout_snapshot"] = {}
            # else it's already a dict from JSONB
            session["started_at"] = session["started_at"].isoformat() if session["started_at"] else None
            session["updated_at"] = session["updated_at"].isoformat() if session["updated_at"] else None
            session["rest_timer_started_at"] = session["rest_timer_started_at"].isoformat() if session["rest_timer_started_at"] else None
            session["total_volume"] = float(session["total_volume"]) if session["total_volume"] else 0

            # Get sets logged in this session
            sets_logged = db.execute(text("""
                SELECT exercise_id, set_index, weight, reps, rpe, notes, created_at
                FROM workout_log
                WHERE active_session_id = :session_id
                ORDER BY created_at ASC
            """), {"session_id": session["id"]}).fetchall()

            session["sets_logged"] = []
            for s in sets_logged:
                log_entry = dict(s._mapping)
                # Serialize datetime
                if log_entry.get("created_at"):
                    log_entry["created_at"] = log_entry["created_at"].isoformat()
                session["sets_logged"].append(log_entry)

            return session

        except Exception as e:
            logger.exception(f"Failed to get active session: {e}")
            return None

    async def log_set(
        self,
        user_id: str,
        weight: Optional[float],
        reps: Optional[int],
        rpe: Optional[int],
        rpe_feeling: Optional[str],
        notes: Optional[str],
        db: Session
    ) -> Dict[str, Any]:
        """
        Log a set for the current active session.

        Updates session progress and returns coaching feedback.

        Args:
            rpe_feeling: Optional feeling-based RPE ("light", "moderate", "hard", "failed")
                         Converted to numeric RPE: light=6, moderate=7.5, hard=9, failed=10
        """
        try:
            # 1. Get active session
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            snapshot = session["workout_snapshot"]
            exercises = snapshot.get("exercises", [])
            current_ex_idx = session["current_exercise_index"]
            current_set_idx = session["current_set_index"]

            if current_ex_idx >= len(exercises):
                raise ValueError("Workout already completed")

            current_exercise = exercises[current_ex_idx]
            exercise_name = current_exercise["name"]
            target_sets = current_exercise["sets"]
            suggested_weight = current_exercise.get("suggested_weight")

            # Convert rpe_feeling to numeric RPE if not explicitly provided
            if rpe is None and rpe_feeling:
                rpe_map = {"light": 6, "moderate": 7, "hard": 9, "failed": 10}
                rpe = rpe_map.get(rpe_feeling, 7)

            # Use suggested weight if not provided
            if weight is None:
                weight = suggested_weight or 0

            # Use middle of rep range if not provided
            if reps is None:
                target_reps = str(current_exercise.get("reps", "8"))
                if "-" in target_reps:
                    reps = int(target_reps.split("-")[0]) + 1
                else:
                    reps = int(target_reps)

            # 2. Insert workout_log entry
            today = date.today()
            log_id = str(uuid.uuid4())
            db.execute(text("""
                INSERT INTO workout_log (
                    id, workout_id, user_id, exercise_id, set_index, weight, reps, rpe, notes,
                    session_date, session_time, active_session_id
                ) VALUES (
                    :id, :workout_id, :user_id, :exercise_id, :set_index, :weight, :reps, :rpe, :notes,
                    :session_date, :session_time, :session_id
                )
            """), {
                "id": log_id,
                "workout_id": session["id"],  # Use active session ID as workout_id
                "user_id": user_id,
                "exercise_id": exercise_name,
                "set_index": current_set_idx + 1,  # 1-indexed
                "weight": weight,
                "reps": reps,
                "rpe": rpe,
                "notes": notes,
                "session_date": today,
                "session_time": datetime.now(),
                "session_id": session["id"]
            })

            # 3. Update session progress
            new_set_idx = current_set_idx + 1
            new_ex_idx = current_ex_idx
            workout_complete = False

            if new_set_idx >= target_sets:
                # Move to next exercise
                new_set_idx = 0
                new_ex_idx = current_ex_idx + 1
                if new_ex_idx >= len(exercises):
                    workout_complete = True

            volume_added = Decimal(str(weight)) * Decimal(str(reps))

            db.execute(text("""
                UPDATE active_workout_session
                SET current_exercise_index = :ex_idx,
                    current_set_index = :set_idx,
                    total_sets_completed = total_sets_completed + 1,
                    total_volume = total_volume + :volume,
                    updated_at = NOW()
                WHERE id = :session_id
            """), {
                "ex_idx": new_ex_idx,
                "set_idx": new_set_idx,
                "volume": volume_added,
                "session_id": session["id"]
            })

            db.commit()

            # 4. Generate coaching feedback (async LLM call)
            feedback = await self._generate_set_feedback(
                exercise_name=exercise_name,
                set_number=current_set_idx + 1,
                total_sets=target_sets,
                weight=weight,
                reps=reps,
                rpe=rpe,
                suggested_weight=suggested_weight,
                is_last_set=(new_set_idx == 0 and not workout_complete),
                workout_complete=workout_complete,
                next_exercise=exercises[new_ex_idx] if not workout_complete and new_ex_idx < len(exercises) else None,
                rest_seconds=current_exercise.get("rest_seconds", 120)
            )

            return {
                "success": True,
                "logged": {
                    "exercise": exercise_name,
                    "set_number": current_set_idx + 1,
                    "weight": weight,
                    "reps": reps,
                    "rpe": rpe
                },
                "coaching_feedback": feedback.get("text", ""),  # Just the text string
                "next_set": {
                    "exercise": exercises[new_ex_idx]["name"] if not workout_complete and new_ex_idx < len(exercises) else None,
                    "set_number": new_set_idx + 1 if not workout_complete else None,
                    "suggested_weight": exercises[new_ex_idx].get("suggested_weight") if not workout_complete and new_ex_idx < len(exercises) else None,
                    "workout_complete": workout_complete,
                    "exercise_complete": new_set_idx == 0 and not workout_complete,
                    "weight_adjustment": feedback.get("weight_adjustment"),
                    "rest_seconds": feedback.get("rest_seconds", 0)
                },
                "total_sets_completed": session["total_sets_completed"] + 1,
                "total_volume": float(session["total_volume"]) + float(volume_added)
            }

        except Exception as e:
            db.rollback()
            logger.exception(f"Failed to log set: {e}")
            raise

    async def _generate_set_feedback(
        self,
        exercise_name: str,
        set_number: int,
        total_sets: int,
        weight: float,
        reps: int,
        rpe: Optional[int],
        suggested_weight: Optional[float],
        is_last_set: bool,
        workout_complete: bool,
        next_exercise: Optional[Dict],
        rest_seconds: int
    ) -> Dict[str, Any]:
        """Generate AI coaching feedback for a logged set using local LLM."""

        weight_adjustment = None

        # Determine weight adjustment based on RPE
        if rpe:
            if rpe <= 6:
                weight_adjustment = 5
            elif rpe >= 9:
                weight_adjustment = -5

        # Build context for LLM
        context = f"""You are Sara, an encouraging fitness coach. Give brief, personalized feedback (1-2 sentences max).

Current situation:
- Exercise: {exercise_name}
- Just completed: Set {set_number} of {total_sets}
- Weight: {weight}lbs, Reps: {reps}
- RPE (effort 1-10): {rpe if rpe else 'not provided'}
- Suggested weight was: {suggested_weight}lbs
"""
        if workout_complete:
            context += "\nThis was the FINAL set of the workout! Congratulate them on finishing."
        elif is_last_set:
            next_name = next_exercise["name"] if next_exercise else "cooldown"
            context += f"\nThis was the last set of {exercise_name}. Next exercise: {next_name}"
        else:
            sets_remaining = total_sets - set_number
            context += f"\n{sets_remaining} sets remaining for this exercise. Rest time: {rest_seconds}s"
            if weight_adjustment:
                if weight_adjustment > 0:
                    context += f"\nSuggest adding {weight_adjustment}lbs - felt easy!"
                else:
                    context += f"\nSuggest dropping {abs(weight_adjustment)}lbs - was tough"

        context += "\n\nRespond with just the coaching message, no quotes or prefixes."

        # Try LLM, fall back to simple template if it fails
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{WORKOUT_LLM_BASE_URL}/chat/completions",
                    json={
                        "model": WORKOUT_LLM_MODEL,
                        "messages": [{"role": "user", "content": context}],
                        "max_tokens": 100,
                        "temperature": 0.7
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    feedback_text = data["choices"][0]["message"]["content"].strip()
                    logger.info(f"[WorkoutCoaching] LLM feedback: {feedback_text}")
                else:
                    logger.warning(f"[WorkoutCoaching] LLM returned {response.status_code}, using fallback")
                    feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds)
        except Exception as e:
            logger.warning(f"[WorkoutCoaching] LLM failed: {e}, using fallback")
            feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds)

        return {
            "text": feedback_text,
            "rest_seconds": rest_seconds if not workout_complete else 0,
            "weight_adjustment": weight_adjustment,
            "workout_complete": workout_complete
        }

    def _fallback_feedback(
        self,
        exercise_name: str,
        set_number: int,
        total_sets: int,
        rpe: Optional[int],
        workout_complete: bool,
        is_last_set: bool,
        next_exercise: Optional[Dict],
        rest_seconds: int
    ) -> str:
        """Simple fallback feedback if LLM is unavailable."""
        if workout_complete:
            return "Great workout! You crushed it. Time to recover."
        elif is_last_set:
            next_name = next_exercise["name"] if next_exercise else "cooldown"
            return f"Nice work on {exercise_name}! Moving on to {next_name}."
        else:
            sets_remaining = total_sets - set_number
            if rpe and rpe <= 6:
                return f"Felt light! Add 5lbs for set {set_number + 1}."
            elif rpe and rpe >= 9:
                return f"That was tough! Consider dropping 5lbs."
            else:
                return f"Good set! {sets_remaining} more to go. Rest {rest_seconds // 60} min."

    async def skip_exercise(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Skip the current exercise and move to the next one."""
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            snapshot = session["workout_snapshot"]
            exercises = snapshot.get("exercises", [])
            current_ex_idx = session["current_exercise_index"]

            new_ex_idx = current_ex_idx + 1
            workout_complete = new_ex_idx >= len(exercises)

            db.execute(text("""
                UPDATE active_workout_session
                SET current_exercise_index = :ex_idx,
                    current_set_index = 0,
                    updated_at = NOW()
                WHERE id = :session_id
            """), {
                "ex_idx": new_ex_idx,
                "session_id": session["id"]
            })
            db.commit()

            skipped_name = exercises[current_ex_idx]["name"]
            next_exercise = exercises[new_ex_idx] if not workout_complete else None

            return {
                "success": True,
                "skipped_exercise": skipped_name,
                "next_exercise": next_exercise["name"] if next_exercise else None,
                "workout_complete": workout_complete
            }

        except Exception as e:
            db.rollback()
            logger.exception(f"Failed to skip exercise: {e}")
            raise

    async def start_rest_timer(
        self,
        user_id: str,
        duration_seconds: int,
        db: Session
    ) -> Dict[str, Any]:
        """Start a rest timer for the current session."""
        try:
            db.execute(text("""
                UPDATE active_workout_session
                SET rest_timer_started_at = NOW(),
                    rest_timer_duration_seconds = :duration,
                    updated_at = NOW()
                WHERE user_id = :user_id AND status = 'active'
            """), {"user_id": user_id, "duration": duration_seconds})
            db.commit()

            return {
                "success": True,
                "duration_seconds": duration_seconds,
                "started_at": datetime.now().isoformat()
            }
        except Exception as e:
            db.rollback()
            raise

    async def get_rest_timer_status(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Get current rest timer status."""
        session = await self.get_active_session(user_id, db)
        if not session:
            return {"is_active": False}

        if not session.get("rest_timer_started_at"):
            return {"is_active": False}

        started_at = datetime.fromisoformat(session["rest_timer_started_at"])
        duration = session.get("rest_timer_duration_seconds", 120)
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        remaining = max(0, duration - elapsed)

        return {
            "is_active": remaining > 0,
            "remaining_seconds": int(remaining),
            "total_seconds": duration
        }

    async def complete_workout(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Complete the active workout and return summary."""
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            # Calculate summary
            duration_minutes = 0
            if session["started_at"]:
                started = datetime.fromisoformat(session["started_at"])
                # Use timezone-aware datetime for comparison
                now = datetime.now(timezone.utc)
                duration_minutes = int((now - started).total_seconds() / 60)

            db.execute(text("""
                UPDATE active_workout_session
                SET status = 'completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = :session_id
            """), {"session_id": session["id"]})
            db.commit()

            return {
                "success": True,
                "summary": {
                    "workout_name": session["workout_snapshot"].get("template_name", "Workout"),
                    "duration_minutes": duration_minutes,
                    "total_sets": session["total_sets_completed"],
                    "total_volume": session["total_volume"],
                    "exercises_completed": session["current_exercise_index"]
                }
            }

        except Exception as e:
            db.rollback()
            raise

    async def abandon_workout(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Abandon the current workout session."""
        try:
            db.execute(text("""
                UPDATE active_workout_session
                SET status = 'abandoned',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE user_id = :user_id AND status = 'active'
            """), {"user_id": user_id})
            db.commit()

            return {"success": True, "message": "Workout abandoned"}
        except Exception as e:
            db.rollback()
            raise

    async def get_workout_context(self, user_id: str, db: Session) -> Optional[str]:
        """
        Generate context string for Sara's system prompt.

        Includes: current exercise, sets done, weight target, last set, rest timer status.
        """
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                return None

            snapshot = session["workout_snapshot"]
            exercises = snapshot.get("exercises", [])
            current_ex_idx = session["current_exercise_index"]
            current_set_idx = session["current_set_index"]
            sets_logged = session.get("sets_logged", [])

            # Calculate elapsed time (use timezone-aware datetime)
            started = datetime.fromisoformat(session["started_at"])
            now = datetime.now(timezone.utc)
            elapsed_minutes = int((now - started).total_seconds() / 60)

            total_sets = snapshot.get("total_sets", 0)
            progress_pct = int((session["total_sets_completed"] / total_sets * 100)) if total_sets > 0 else 0

            lines = [
                f"**Workout**: {snapshot.get('template_name', 'Workout')}",
                f"**Status**: In Progress ({elapsed_minutes} min)",
                f"**Progress**: {session['total_sets_completed']}/{total_sets} sets ({progress_pct}%)",
                ""
            ]

            # Current exercise info
            if current_ex_idx < len(exercises):
                current_ex = exercises[current_ex_idx]
                lines.append(f"### Current Exercise: {current_ex['name']}")
                lines.append(f"- **Set**: {current_set_idx + 1} of {current_ex['sets']}")
                lines.append(f"- **Target**: {current_ex['reps']} reps @ RPE {current_ex.get('rpe_target', 7)}")

                if current_ex.get("suggested_weight"):
                    lines.append(f"- **Suggested Weight**: {current_ex['suggested_weight']} lbs")
                if current_ex.get("progression_note"):
                    lines.append(f"- **Note**: {current_ex['progression_note']}")

                # Last session data
                if current_ex.get("last_session"):
                    last = current_ex["last_session"]
                    avg_weight = sum(last["weights"]) / len(last["weights"]) if last["weights"] else 0
                    lines.append(f"- **Last Session**: {avg_weight:.0f} lbs x {last['reps']} (avg RPE {last['avg_rpe']:.1f})")
            else:
                lines.append("### Workout Complete!")

            # Last set logged
            if sets_logged:
                last_set = sets_logged[-1]
                lines.append("")
                lines.append(f"### Last Set Logged: {last_set['exercise_id']} - {last_set['weight']}lbs x {last_set['reps']}" +
                           (f" @ RPE {last_set['rpe']}" if last_set.get('rpe') else ""))

            # Rest timer
            timer_status = await self.get_rest_timer_status(user_id, db)
            if timer_status.get("is_active"):
                lines.append("")
                lines.append(f"### Rest Timer: {timer_status['remaining_seconds']}s remaining")

            # Upcoming exercises
            remaining_exercises = exercises[current_ex_idx + 1:current_ex_idx + 4]
            if remaining_exercises:
                lines.append("")
                lines.append("### Up Next:")
                for i, ex in enumerate(remaining_exercises, 1):
                    lines.append(f"{i}. {ex['name']} ({ex['sets']} sets)")

            return "\n".join(lines)

        except Exception as e:
            logger.exception(f"Failed to generate workout context: {e}")
            return None


# Singleton instance
workout_session_service = WorkoutSessionService()
