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

# Local LLM for workout coaching — centralized config
from app.core.llm_config import llm_config as _llm_cfg
WORKOUT_LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", _llm_cfg.primary_url)
WORKOUT_LLM_MODEL = os.getenv("WORKOUT_LLM_MODEL", os.getenv("OPENAI_MODEL", _llm_cfg.fast_model))


class WorkoutSessionService:
    """Manages active workout sessions for real-time coaching"""

    def _name_counts(self, session_id: str, db: Session) -> Dict[str, int]:
        """Logged-set counts per exercise name for a session (from workout_log)."""
        rows = db.execute(text("""
            SELECT exercise_id, COUNT(*) AS c
            FROM workout_log
            WHERE active_session_id = :sid
            GROUP BY exercise_id
        """), {"sid": session_id}).fetchall()
        return {r.exercise_id: int(r.c) for r in rows}

    def _effective_name(self, ex: Dict) -> str:
        """The exercise identity used for logging + history.

        When the user records the actual machine/variation they used (e.g. "Hack
        Squat" for a "Squat" slot), that variant becomes the identity so its
        weights are tracked separately and don't corrupt the base lift's history.
        """
        variant = (ex.get("variant") or "").strip()
        return variant or ex.get("name") or ""

    def _completed_for(self, exercises: List[Dict], name_counts: Dict[str, int], idx: int) -> int:
        """Completed sets for the exercise at idx, capped at its target sets."""
        if idx < 0 or idx >= len(exercises):
            return 0
        ex = exercises[idx]
        target = ex.get("sets", 0) or 0
        return min(name_counts.get(self._effective_name(ex), 0), target)

    def _compute_suggestion(
        self, user_id: str, exercise_name: str, target_reps: Any, is_deload: bool, db: Session
    ) -> Dict[str, Any]:
        """Suggested weight + last-session data for one exercise name.

        Delegates to the single progression brain in `progressive_overload`
        (flat-increment, RPE-gated, recovery-aware, reading `workout_log`) so
        in-session coaching and the /weight-suggestion endpoint never diverge.
        Returns {suggested_weight, progression_note, last_session}.
        """
        from app.services.progressive_overload import (
            fetch_last_session, compute_progression, get_morning_recovery,
        )

        # Morning recovery snapshot — poor sleep/HRV/soreness holds weight
        # instead of auto-adding. Frozen at the morning sync on purpose, so a
        # midday HealthKit update can't shift the day's prescription.
        recovery_data = get_morning_recovery(db, user_id, date.today())

        last_session = fetch_last_session(db, user_id, exercise_name)
        prog = compute_progression(
            last_session, target_reps, exercise_name, is_deload, recovery_data
        )
        return {
            "suggested_weight": prog["suggested_weight"],
            "progression_note": prog["note"],
            "last_session": prog["last_session"],
        }

    def _next_incomplete_index(
        self, exercises: List[Dict], name_counts: Dict[str, int], from_idx: int
    ) -> Optional[int]:
        """Next exercise (searching forward, wrapping) that still has sets left.

        Returns None when every exercise has hit its target — i.e. workout done.
        Wrapping is what lets a skipped or earlier exercise be resumed later.
        """
        n = len(exercises)
        for step in range(1, n + 1):
            j = (from_idx + step) % n
            target = exercises[j].get("sets", 0) or 0
            if self._completed_for(exercises, name_counts, j) < target:
                return j
        return None

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
            raw_ex = template.get("exercises") or "[]"
            if isinstance(raw_ex, str):
                exercises = json.loads(raw_ex)
            else:
                exercises = raw_ex or []

            # Determine deload state for today (used to scale sets + suggested weights below)
            from app.services.progressive_overload import get_deload_state
            deload = get_deload_state(db=db, user_id=user_id, on_date=date.today())
            is_deload = deload["is_deload"]

            # 3. Calculate weight suggestions for each exercise (reuse workout_suggest logic)
            exercise_snapshots = []
            for exercise_spec in exercises:
                exercise_name = exercise_spec.get("name")
                target_sets = exercise_spec.get("sets", 3)
                target_reps = exercise_spec.get("reps", "8-10")
                target_rpe = exercise_spec.get("rpe_target", 7)
                rest_seconds = exercise_spec.get("rest_seconds", 120)
                # Advanced execution markers (may be absent on legacy templates)
                metric_type = exercise_spec.get("metric_type", "reps")
                is_per_side = bool(exercise_spec.get("is_per_side", False))
                superset_group = exercise_spec.get("superset_group")
                set_technique = exercise_spec.get("set_technique")
                exercise_notes = exercise_spec.get("notes")

                # Weight suggestion + last-session data, scoped to this exercise.
                suggestion = self._compute_suggestion(user_id, exercise_name, target_reps, is_deload, db)

                # Apply deload set scaling (weight scaling handled in _compute_suggestion).
                effective_sets = target_sets
                if is_deload:
                    try:
                        effective_sets = max(2, int(target_sets) // 2)
                    except (TypeError, ValueError):
                        effective_sets = target_sets

                exercise_snapshots.append({
                    "name": exercise_name,
                    "variant": None,  # set mid-workout if the user logs a machine/variation
                    "sets": effective_sets,
                    "sets_original": target_sets if is_deload else None,
                    "reps": target_reps,
                    "rpe_target": target_rpe,
                    "rest_seconds": rest_seconds,
                    "notes": exercise_notes,
                    "metric_type": metric_type,
                    "is_per_side": is_per_side,
                    "superset_group": superset_group,
                    "set_technique": set_technique,
                    "suggested_weight": suggestion["suggested_weight"],
                    "progression_note": suggestion["progression_note"],
                    "last_session": suggestion["last_session"],
                })

            # 4. Create workout snapshot
            workout_snapshot = {
                "template_id": template_id,
                "template_name": template["name"],
                "template_notes": template.get("notes"),
                "exercises": exercise_snapshots,
                "total_sets": sum(e["sets"] for e in exercise_snapshots),
                "is_deload": is_deload,
                "week_of_phase": deload.get("week_of_phase"),
                "deload_week": deload.get("deload_week"),
                "phase_name": deload.get("phase_name"),
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

            # Annotate each snapshot exercise with how many sets are already logged,
            # so the client can show completion / partial progress regardless of the
            # order exercises were done in (the cursor alone no longer implies "done").
            name_counts: Dict[str, int] = {}
            for entry in session["sets_logged"]:
                ex_name = entry.get("exercise_id")
                name_counts[ex_name] = name_counts.get(ex_name, 0) + 1
            for ex in (session["workout_snapshot"].get("exercises") or []):
                target = ex.get("sets", 0) or 0
                ex["completed_sets"] = min(name_counts.get(self._effective_name(ex), 0), target)

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
            base_name = current_exercise["name"]
            # Log against the machine/variation if the user set one, so its weights
            # build their own history instead of corrupting the base lift's.
            exercise_name = self._effective_name(current_exercise)
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
            # Preserve the link back to the templated lift when a variant is used,
            # so this set isn't orphaned from "Squat" for future analytics.
            variant = (current_exercise.get("variant") or "").strip() or None
            flags = json.dumps({"base_exercise": base_name, "variant": variant}) if variant else None
            db.execute(text("""
                INSERT INTO workout_log (
                    id, workout_id, user_id, exercise_id, set_index, weight, reps, rpe, notes,
                    session_date, session_time, active_session_id, flags
                ) VALUES (
                    :id, :workout_id, :user_id, :exercise_id, :set_index, :weight, :reps, :rpe, :notes,
                    :session_date, :session_time, :session_id, CAST(:flags AS json)
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
                # Real UTC instant — the container runs in ET, so a naive
                # datetime.now() would store wall-clock ET as if UTC (4-5h early)
                # and break the Apple-Watch time-overlap meld.
                "session_time": datetime.now(timezone.utc),
                "session_id": session["id"],
                "flags": flags,
            })

            # 3. Recompute per-exercise progress from logged sets, then decide
            #    where the cursor goes. Counting from workout_log (rather than a
            #    single incrementing pointer) is what supports doing exercises in
            #    any order and skipping/returning — see _next_incomplete_index.
            name_counts = self._name_counts(session["id"], db)
            current_done = self._completed_for(exercises, name_counts, current_ex_idx)
            exercise_complete = current_done >= (target_sets or 0)

            new_ex_idx = current_ex_idx
            new_set_idx = current_done
            workout_complete = False
            next_idx = None

            if exercise_complete:
                next_idx = self._next_incomplete_index(exercises, name_counts, current_ex_idx)
                if next_idx is None:
                    workout_complete = True
                else:
                    new_ex_idx = next_idx
                    new_set_idx = self._completed_for(exercises, name_counts, next_idx)

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

            # 3b. PR detection — celebrate a new estimated-1RM best for this lift.
            #     Reuses the same check the manual-logging path uses.
            pr_result = None
            try:
                if weight and reps and float(weight) > 0 and int(reps) > 0:
                    from app.routes.fitness import check_and_record_pr
                    pr_result = await check_and_record_pr(
                        db=db, user_id=user_id, exercise_name=exercise_name,
                        weight=weight, reps=reps, achieved_at=today, workout_set_id=log_id,
                    )
                    db.commit()
                    if pr_result and pr_result.get("is_pr"):
                        db.execute(text("UPDATE workout_log SET is_pr = true WHERE id = :id"),
                                   {"id": log_id})
                        db.commit()
            except Exception as e:
                logger.warning(f"[WorkoutMode] PR check failed (non-fatal): {e}")

            # 4. Generate coaching feedback (async LLM call). Rest length scales
            #    with the intensity of the set just logged (RPE) + lift type.
            smart_rest = self._smart_rest_seconds(exercise_name, rpe)
            feedback = await self._generate_set_feedback(
                exercise_name=exercise_name,
                set_number=current_set_idx + 1,
                total_sets=target_sets,
                weight=weight,
                reps=reps,
                rpe=rpe,
                suggested_weight=suggested_weight,
                is_last_set=(exercise_complete and not workout_complete),
                workout_complete=workout_complete,
                next_exercise=exercises[next_idx] if next_idx is not None else None,
                rest_seconds=smart_rest
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
                "pr": pr_result if (pr_result and pr_result.get("is_pr")) else None,
                "coaching_feedback": feedback.get("text", ""),  # Just the text string
                "next_set": {
                    "exercise": exercises[new_ex_idx]["name"] if not workout_complete and new_ex_idx < len(exercises) else None,
                    "set_number": new_set_idx + 1 if not workout_complete else None,
                    "suggested_weight": exercises[new_ex_idx].get("suggested_weight") if not workout_complete and new_ex_idx < len(exercises) else None,
                    "workout_complete": workout_complete,
                    "exercise_complete": exercise_complete and not workout_complete,
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

    @staticmethod
    def _smart_rest_seconds(exercise_name: Optional[str], rpe: Optional[int]) -> int:
        """Rest length scaled to the set's intensity (RPE) + lift type.

        Hard compound set → ~3 min; an easy isolation set → ~1 min. Replaces the
        old flat 180s/90s so rest matches how taxing the set actually was.
        """
        name = (exercise_name or "").lower()
        is_compound = any(k in name for k in [
            "squat", "deadlift", "bench", "press", "row", "pull-up", "pullup",
            "chin-up", "chinup", "lunge", "clean", "snatch", "hip thrust",
        ])
        r = rpe if rpe else 7
        if r >= 9:
            base = 180
        elif r >= 8:
            base = 150
        elif r >= 7:
            base = 120
        else:
            base = 75
        base += 30 if is_compound else -15
        return max(45, min(base, 210))

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
                        "temperature": 0.7,
                        # Qwen returns empty/echoed content if thinking is on for
                        # short outputs — this is what leaked the raw prompt into
                        # the coaching popup.
                        "chat_template_kwargs": {"enable_thinking": False},
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    feedback_text = (data["choices"][0]["message"].get("content") or "").strip()
                    logger.info(f"[WorkoutCoaching] LLM feedback: {feedback_text}")
                    # Guard: discard empty output or the model echoing the
                    # instruction prompt back as "feedback".
                    low = feedback_text.lower()
                    if (not feedback_text or len(feedback_text) > 280
                            or "you are sara" in low or "current situation" in low
                            or "coaching message" in low or "respond with" in low):
                        logger.warning("[WorkoutCoaching] discarding echoed/empty LLM output, using fallback")
                        feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds)
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
        """Skip the current exercise and move to the next incomplete one.

        The skipped exercise is NOT marked done — it stays incomplete so the user
        can come back to it later (e.g. a machine was busy). Only when every other
        exercise is finished does this report the workout as complete.
        """
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            snapshot = session["workout_snapshot"]
            exercises = snapshot.get("exercises", [])
            current_ex_idx = session["current_exercise_index"]
            if not exercises:
                return {"success": True, "skipped_exercise": None, "next_exercise": None, "workout_complete": True}

            name_counts = self._name_counts(session["id"], db)
            next_idx = self._next_incomplete_index(exercises, name_counts, current_ex_idx)
            workout_complete = next_idx is None
            # If nothing else is incomplete, stay put rather than running off the end.
            new_ex_idx = current_ex_idx if next_idx is None else next_idx
            new_set_idx = self._completed_for(exercises, name_counts, new_ex_idx)

            db.execute(text("""
                UPDATE active_workout_session
                SET current_exercise_index = :ex_idx,
                    current_set_index = :set_idx,
                    updated_at = NOW()
                WHERE id = :session_id
            """), {
                "ex_idx": new_ex_idx,
                "set_idx": new_set_idx,
                "session_id": session["id"]
            })
            db.commit()

            skipped_name = exercises[current_ex_idx]["name"] if current_ex_idx < len(exercises) else None
            next_exercise = exercises[next_idx] if next_idx is not None else None

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

    async def select_exercise(self, user_id: str, exercise_index: int, db: Session) -> Dict[str, Any]:
        """Jump the active cursor to any exercise so they can be done in any order.

        Set progress for the chosen exercise is recomputed from what's already been
        logged, so returning to a partially-done exercise resumes mid-way.
        """
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            exercises = session["workout_snapshot"].get("exercises", [])
            if exercise_index < 0 or exercise_index >= len(exercises):
                raise ValueError(f"Exercise index {exercise_index} out of range")

            name_counts = self._name_counts(session["id"], db)
            new_set_idx = self._completed_for(exercises, name_counts, exercise_index)

            db.execute(text("""
                UPDATE active_workout_session
                SET current_exercise_index = :ex_idx,
                    current_set_index = :set_idx,
                    updated_at = NOW()
                WHERE id = :session_id
            """), {
                "ex_idx": exercise_index,
                "set_idx": new_set_idx,
                "session_id": session["id"]
            })
            db.commit()

            return {
                "success": True,
                "current_exercise_index": exercise_index,
                "current_set_index": new_set_idx,
                "exercise": exercises[exercise_index]["name"],
            }

        except Exception as e:
            db.rollback()
            logger.exception(f"Failed to select exercise: {e}")
            raise

    async def set_exercise_variant(
        self, user_id: str, exercise_index: int, variant: Optional[str], db: Session
    ) -> Dict[str, Any]:
        """Record the machine/variation used for an exercise.

        The variant becomes the identity used for logging + suggestions, so e.g.
        hack-squat weights don't get logged against (and tank) your barbell squat.
        Recomputes the suggested weight / last-session for the variant and persists
        it onto the session snapshot.
        """
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            snapshot = session["workout_snapshot"]
            exercises = snapshot.get("exercises", [])
            if exercise_index < 0 or exercise_index >= len(exercises):
                raise ValueError(f"Exercise index {exercise_index} out of range")

            ex = exercises[exercise_index]
            clean = (variant or "").strip()
            # A variant matching the base name (case-insensitive) is just the base lift.
            ex["variant"] = None if (not clean or clean.lower() == (ex.get("name") or "").lower()) else clean

            # Re-scope suggestion + last-session to whatever they're actually doing.
            effective = self._effective_name(ex)
            is_deload = bool(snapshot.get("is_deload"))
            suggestion = self._compute_suggestion(user_id, effective, ex.get("reps", "8-10"), is_deload, db)
            ex["suggested_weight"] = suggestion["suggested_weight"]
            ex["progression_note"] = suggestion["progression_note"]
            ex["last_session"] = suggestion["last_session"]

            db.execute(text("""
                UPDATE active_workout_session
                SET workout_snapshot = CAST(:snapshot AS jsonb),
                    updated_at = NOW()
                WHERE id = :session_id
            """), {"snapshot": json.dumps(snapshot), "session_id": session["id"]})

            # If they re-scoped the exercise they're on, resync its set cursor.
            if exercise_index == session["current_exercise_index"]:
                name_counts = self._name_counts(session["id"], db)
                new_set_idx = self._completed_for(exercises, name_counts, exercise_index)
                db.execute(text("""
                    UPDATE active_workout_session SET current_set_index = :set_idx WHERE id = :session_id
                """), {"set_idx": new_set_idx, "session_id": session["id"]})

            db.commit()

            return {
                "success": True,
                "exercise_index": exercise_index,
                "variant": ex["variant"],
                "effective_name": effective,
                "suggested_weight": ex["suggested_weight"],
                "last_session": ex["last_session"],
            }

        except Exception as e:
            db.rollback()
            logger.exception(f"Failed to set exercise variant: {e}")
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
                "started_at": datetime.now(timezone.utc).isoformat()
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

    # HKWorkoutActivityType raw values → friendly names (subset we care about).
    _ACTIVITY_NAMES = {
        "13": "Cycling", "16": "Elliptical", "35": "Functional Strength",
        "37": "Running", "44": "Rowing", "50": "Strength Training",
        "52": "Walking", "63": "HIIT",
    }

    def _meld_external_workout(self, db: Session, user_id: str, started, ended) -> Optional[Dict[str, Any]]:
        """Apple-Watch HR/calories for the same training day as this strength session.

        Matches by ET calendar day rather than strict time overlap, so it's robust
        to clock skew between Sara's logged times and the watch. Prefers a
        strength-type watch workout, then the closest start time. Returns None if
        nothing has synced for that day yet.
        """
        if not started:
            return None
        try:
            from zoneinfo import ZoneInfo
            from datetime import timedelta
            et = ZoneInfo("America/New_York")
            rows = db.execute(text("""
                SELECT activity_type, avg_heart_rate, max_heart_rate, min_heart_rate,
                       total_energy_kcal, total_distance_m, duration_seconds, started_at
                FROM external_workout
                WHERE user_id = :uid
                  AND started_at >= :lo AND started_at <= :hi
            """), {"uid": user_id, "lo": started - timedelta(days=1),
                   "hi": (ended or started) + timedelta(days=1)}).fetchall()

            sess_day = started.astimezone(et).date()
            strength = {"50", "35", "63"}
            best, best_key = None, (-1, 1.0)
            for r in rows:
                if r.started_at.astimezone(et).date() != sess_day:
                    continue
                gap = abs((r.started_at - started).total_seconds())
                key = (1 if str(r.activity_type) in strength else 0, -gap)
                if best is None or key > best_key:
                    best, best_key = r, key
            if not best:
                return None
            return {
                "activity": self._ACTIVITY_NAMES.get(str(best.activity_type), "Workout"),
                "avg_heart_rate": best.avg_heart_rate,
                "max_heart_rate": best.max_heart_rate,
                "min_heart_rate": best.min_heart_rate,
                "calories": round(float(best.total_energy_kcal)) if best.total_energy_kcal is not None else None,
                "distance_m": round(float(best.total_distance_m)) if best.total_distance_m is not None else None,
                "duration_min": round(best.duration_seconds / 60) if best.duration_seconds else None,
            }
        except Exception as e:
            logger.warning(f"[WorkoutMode] external-workout meld failed: {e}")
            return None

    async def complete_workout(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Complete the active workout and return summary."""
        try:
            session = await self.get_active_session(user_id, db)
            if not session:
                raise ValueError("No active workout session")

            # Calculate summary
            now = datetime.now(timezone.utc)
            started = None
            duration_minutes = 0
            if session["started_at"]:
                started = datetime.fromisoformat(session["started_at"])
                duration_minutes = int((now - started).total_seconds() / 60)

            db.execute(text("""
                UPDATE active_workout_session
                SET status = 'completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = :session_id
            """), {"session_id": session["id"]})
            db.commit()

            # Meld in Apple-Watch HR/calories for the same time window (if synced).
            heart_rate = self._meld_external_workout(db, user_id, started, now)

            return {
                "success": True,
                "session_id": session["id"],
                "completed_at": now.isoformat(),
                "summary": {
                    "workout_name": session["workout_snapshot"].get("template_name", "Workout"),
                    "duration_minutes": duration_minutes,
                    "total_sets": session["total_sets_completed"],
                    "total_volume": session["total_volume"],
                    "exercises_completed": session["current_exercise_index"],
                    "heart_rate": heart_rate,
                }
            }

        except Exception as e:
            db.rollback()
            raise

    async def abandon_workout(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Abandon the current workout session.

        An abandoned workout is NOT saved: any sets logged mid-session (which are
        committed to workout_log as they happen) are deleted, along with the empty
        workout shell created at start. Only the active_workout_session row is kept,
        marked 'abandoned', so it no longer counts as active.
        """
        try:
            session = await self.get_active_session(user_id, db)
            session_id = session["id"] if session else None

            if session_id:
                # Drop the logged sets first (workout_log.workout_id FKs workout.id),
                # then the workout shell — nothing from this session lands in history.
                db.execute(
                    text("DELETE FROM workout_log WHERE active_session_id = :sid"),
                    {"sid": session_id},
                )
                db.execute(
                    text("DELETE FROM workout WHERE id = :sid"),
                    {"sid": session_id},
                )

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
