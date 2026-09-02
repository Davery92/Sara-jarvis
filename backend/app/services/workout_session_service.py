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
from typing import Optional, Dict, List, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Local LLM for workout coaching — centralized config. WORKOUT_LLM_MODEL/
# _BASE_URL are a deliberate per-feature override; absent that, resolve the
# "utility" capability at call time (Arc 6 broker migration, work-order item
# 2.5, 2026-07-30) instead of caching an OPENAI_MODEL env read at import time,
# which would never see a live rename_model() DB update.
from app.core.llm_config import llm_config as _llm_cfg
_WORKOUT_LLM_MODEL_OVERRIDE = os.getenv("WORKOUT_LLM_MODEL")
# Dedicated override only — OPENAI_BASE_URL is the chat lane in the backend process.
_WORKOUT_LLM_BASE_URL_OVERRIDE = os.getenv("WORKOUT_LLM_BASE_URL")


def _resolve_workout_llm() -> tuple:
    if _WORKOUT_LLM_MODEL_OVERRIDE and _WORKOUT_LLM_BASE_URL_OVERRIDE:
        return _WORKOUT_LLM_BASE_URL_OVERRIDE, _WORKOUT_LLM_MODEL_OVERRIDE
    try:
        # Fast tier (her A3B, ~0.7s): in-session coaching lines are ≤100 tokens
        # and latency-sensitive; the Mac lanes are for long-form / chat.
        base_url = _WORKOUT_LLM_BASE_URL_OVERRIDE or _llm_cfg.fast_model_url
        model = _WORKOUT_LLM_MODEL_OVERRIDE or _llm_cfg.fast_model
        return base_url, model
    except Exception:
        return (
            _WORKOUT_LLM_BASE_URL_OVERRIDE or _llm_cfg.fast_model_url,
            _WORKOUT_LLM_MODEL_OVERRIDE or _llm_cfg.fast_model,
        )

_VOICE_SNIPPET_CACHE: Dict[str, Optional[str]] = {"text": None}
_VOICE_SNIPPET_FALLBACK = (
    "You are Sara, David's personal AI assistant — Syl's bubbly, curious energy with "
    "Cortana's competence. Warm, sharp, genuinely invested in what David's doing."
)


def _get_voice_snippet() -> str:
    """SARA_MIND_V2 §3.10: mid-set coaching draws from the SAME shared voice
    doc as chat and background compose, "so mid-set Sara is the same Sara
    who texted you about Jim." This is the low-latency coaching lane
    (must render in ~1-2s, may not queue behind judge/compose) — it can't
    afford a DB round-trip or a full World Brief render per set, but one
    small file read cached for the process lifetime costs nothing after
    the first call.
    """
    if _VOICE_SNIPPET_CACHE["text"] is None:
        try:
            from pathlib import Path
            doc_path = Path(__file__).resolve().parent.parent / "prompts" / "sara_voice.md"
            content = doc_path.read_text()
            start = content.find("## Who Sara Is")
            end = content.find("## Anti-examples")
            snippet = content[start:end].strip() if (start >= 0 and end > start) else ""
            _VOICE_SNIPPET_CACHE["text"] = snippet[:1200] or _VOICE_SNIPPET_FALLBACK
        except Exception:
            _VOICE_SNIPPET_CACHE["text"] = _VOICE_SNIPPET_FALLBACK
    return _VOICE_SNIPPET_CACHE["text"]


class WorkoutSessionService:
    """Manages active workout sessions for real-time coaching"""

    def _name_counts(self, session_id: str, db: Session) -> Dict[str, int]:
        """Live working-set counts per exercise name (from `workout_log`).

        Warm-ups, drop segments and undone sets are excluded — the single
        definition of "how many sets are done" lives in `workout_recalc`
        (2026-07-27 plan §6.4) so this and the v2 service cannot diverge.
        """
        from app.services.workout_recalc import working_counts
        return working_counts(db, session_id)

    def _effective_name(self, ex: Dict) -> str:
        """The exercise identity used for logging + history.

        When the user records the actual machine/variation they used (e.g. "Hack
        Squat" for a "Squat" slot), that variant becomes the identity so its
        weights are tracked separately and don't corrupt the base lift's history.
        """
        from app.services.workout_recalc import effective_name
        return effective_name(ex)

    def _completed_for(self, exercises: List[Dict], name_counts: Dict[str, int], idx: int) -> int:
        """Completed working sets at idx, capped at its *effective* target.

        Effective, not prescribed: a set David added during this workout has to
        be reachable, or Add Set would leave the cursor thinking the exercise
        was already finished.
        """
        from app.services.workout_recalc import completed_for
        return completed_for(exercises, name_counts, idx)

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
        from app.services.workout_recalc import next_incomplete_index
        return next_incomplete_index(exercises, name_counts, from_idx)

    async def start_workout(
        self,
        user_id: str,
        template_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """Start a workout — compatibility adapter over the v2 command service.

        The session snapshot, weight suggestions and conflict handling all live
        in `workout_command_service` now (§6.5: one mutation implementation, not
        a phone path and a Watch path that drift). This method only reshapes the
        v2 projection back into the response the current iOS app expects.

        Conflict policy is the one behavioural difference and it is flag-gated:
        with WORKOUT_COMMAND_V2_ENABLED off, Start still implicitly abandons a
        running workout exactly as it does today; with it on, Start refuses and
        raises so the caller can offer Resume/End (§6.6).
        """
        from app.services.workout_command_service import workout_command_service, _v2_enabled

        await workout_command_service.start(
            db, user_id, template_id,
            origin_device="phone",
            on_conflict="error" if _v2_enabled() else "abandon",
        )

        session = await self.get_active_session(user_id, db)
        if not session:
            raise ValueError("Failed to start workout session")
        return {
            "id": session["id"],
            "status": session["status"],
            "started_at": session["started_at"],
            "template_name": session["workout_snapshot"].get("template_name"),
            "workout_snapshot": session["workout_snapshot"],
            "current_exercise_index": session["current_exercise_index"],
            "current_set_index": session["current_set_index"],
            "total_sets_completed": session["total_sets_completed"],
        }

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
                    total_sets_completed, total_volume, notes, updated_at,
                    -- Additive for cross-device control: the phone needs the
                    -- version to stamp expected_version on its commands, and
                    -- the Watch/HealthKit state to render "tracking on Watch".
                    version, origin_device, healthkit_state, healthkit_workout_uuid
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

            # Sets logged in this session, including their kind and grouping so
            # the phone can render a drop-set series as one working set rather
            # than three (2026-07-27 plan §6.1). Voided rows come along with an
            # explicit flag: View/Edit shows them struck, nothing counts them.
            sets_logged = db.execute(text("""
                SELECT id, exercise_id, set_index, weight, reps, rpe, notes, created_at,
                       set_kind, parent_set_id, set_group_id, group_sequence,
                       counts_toward_target, voided_at, void_reason, is_pr
                FROM workout_log
                WHERE active_session_id = :session_id
                ORDER BY created_at ASC, group_sequence ASC
            """), {"session_id": session["id"]}).fetchall()

            session["sets_logged"] = []
            for s in sets_logged:
                log_entry = dict(s._mapping)
                # Serialize datetime
                if log_entry.get("created_at"):
                    log_entry["created_at"] = log_entry["created_at"].isoformat()
                log_entry["voided"] = log_entry.pop("voided_at", None) is not None
                session["sets_logged"].append(log_entry)

            # Annotate each snapshot exercise with how many sets are already logged,
            # so the client can show completion / partial progress regardless of the
            # order exercises were done in (the cursor alone no longer implies "done").
            from app.services.workout_recalc import (
                effective_name, prescribed_sets_for, target_sets_for,
            )
            name_counts: Dict[str, int] = {}
            drop_counts: Dict[str, int] = {}
            for entry in session["sets_logged"]:
                if entry.get("voided"):
                    continue
                ex_name = entry.get("exercise_id")
                if entry.get("counts_toward_target"):
                    name_counts[ex_name] = name_counts.get(ex_name, 0) + 1
                if entry.get("set_kind") == "drop":
                    drop_counts[ex_name] = drop_counts.get(ex_name, 0) + 1
            for ex in (session["workout_snapshot"].get("exercises") or []):
                name = effective_name(ex)
                # Read both before writing either: `sets` is an input to
                # `target_sets_for`, and overwriting it first would fold
                # `sets_added` in twice.
                prescribed = prescribed_sets_for(ex)
                effective = target_sets_for(ex)
                ex["completed_sets"] = min(name_counts.get(name, 0), effective)
                ex["completed_drop_segments"] = drop_counts.get(name, 0)
                # The phone's existing panel reads `sets`; keep it the number of
                # sets to actually do, and expose the untouched prescription
                # alongside it so "4 sets (3 prescribed)" stays derivable.
                ex["prescribed_sets"] = prescribed
                ex["sets"] = effective

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
        """Log a set — compatibility adapter over the v2 command service.

        The set itself is written by `workout_command_service.execute`, so the
        phone and the Watch go through the same idempotent, version-checked
        path and a retried request cannot produce two rows.

        Coaching is the one place this adapter still differs from v2: today's
        phone UI reads `coaching_feedback` straight off this response, so while
        WORKOUT_COMMAND_V2_ENABLED is off we still wait for the sentence here.
        Once it is on, the set is acknowledged immediately and the sentence
        arrives as a workout event instead (§6.7).

        Args:
            rpe_feeling: feeling-based effort ("easy"/"right"/"hard", or the
                         older "light"/"moderate"/"hard"/"failed").
        """
        from app.services.workout_command_service import workout_command_service, _v2_enabled

        result = await workout_command_service.execute(db, user_id, {
            "command_id": str(uuid.uuid4()),
            "kind": "log_set",
            "origin_device": "phone",
            "payload": {
                "weight": weight, "reps": reps, "rpe": rpe,
                "rpe_feeling": rpe_feeling, "notes": notes,
            },
        })

        logged = result.get("logged") or {}
        projection = result.get("projection") or {}
        progress = projection.get("progress") or {}
        cursor = projection.get("cursor") or {}
        exercises = projection.get("exercises") or []
        workout_complete = bool(result.get("workout_complete"))
        next_idx = cursor.get("exercise_index")
        next_ex = exercises[next_idx] if (not workout_complete and isinstance(next_idx, int)
                                          and next_idx < len(exercises)) else None

        coaching_text = ""
        weight_adjustment = None
        if not _v2_enabled():
            snapshot_ex = next_ex or {}
            feedback = await self._generate_set_feedback(
                exercise_name=logged.get("exercise") or "",
                set_number=logged.get("set_number") or 1,
                total_sets=snapshot_ex.get("target_sets") or 0,
                weight=logged.get("weight") or 0,
                reps=logged.get("reps") or 0,
                rpe=logged.get("rpe"),
                suggested_weight=snapshot_ex.get("approved_weight"),
                is_last_set=bool(result.get("exercise_complete")),
                workout_complete=workout_complete,
                next_exercise={"name": snapshot_ex.get("name")} if snapshot_ex.get("name") else None,
                rest_seconds=result.get("rest_seconds") or 0,
            )
            coaching_text = feedback.get("text", "")
            weight_adjustment = feedback.get("weight_adjustment")

        return {
            "success": True,
            "logged": {
                "exercise": logged.get("exercise"),
                "set_number": logged.get("set_number"),
                "weight": logged.get("weight"),
                "reps": logged.get("reps"),
                "rpe": logged.get("rpe"),
            },
            "pr": result.get("pr"),
            "coaching_feedback": coaching_text,
            "next_set": {
                "exercise": next_ex.get("name") if next_ex else None,
                "set_number": (cursor.get("set_index") or 0) + 1 if not workout_complete else None,
                "suggested_weight": next_ex.get("approved_weight") if next_ex else None,
                "workout_complete": workout_complete,
                "exercise_complete": bool(result.get("exercise_complete")),
                "weight_adjustment": weight_adjustment,
                "rest_seconds": result.get("rest_seconds") or 0,
            },
            # Sara may recommend, never apply — the phone surfaces this as
            # Approve / Keep current (§9.5).
            "proposal": result.get("proposal"),
            "session_version": projection.get("version"),
            "total_sets_completed": progress.get("completed_sets"),
            "total_volume": progress.get("total_volume"),
        }

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
        rest_seconds: int,
        set_kind: str = "working",
        drop_segment: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate AI coaching feedback for a logged set using local LLM.

        `set_kind` matters more than it looks. A drop segment and a warm-up are
        both intentionally lighter than the working weight, and an LLM told only
        "135 lbs, suggested 185" will read either as a bad set and say so
        (2026-07-27 plan §8). It is told what the set was for instead.
        """

        weight_adjustment = None

        # Determine weight adjustment based on RPE. Only a working set can move
        # the prescription: a warm-up is submaximal by design and a drop segment
        # is deliberately below the working weight, so neither is evidence about
        # what David should be lifting.
        if rpe and set_kind == "working":
            if rpe <= 6:
                weight_adjustment = 5
            elif rpe >= 9:
                weight_adjustment = -5

        # Build context for LLM. SARA_MIND_V2 §3.10: this is the ENGAGED
        # state of the same mind that texts David about Jim, not a separate
        # "fitness coach" persona — the voice snippet below is the shared
        # doc's actual identity/tone, not a generic coach framing.
        context = f"""{_get_voice_snippet()}

Right now you're coaching David mid-set, in your own voice above — not a generic "encouraging fitness coach" persona. Give brief, personalized feedback (1-2 sentences max).

Current situation:
- Exercise: {exercise_name}
- Just completed: Set {set_number} of {total_sets}
- Weight: {weight}lbs, Reps: {reps}
- RPE (effort 1-10): {rpe if rpe else 'not provided'}
- Suggested weight was: {suggested_weight}lbs
"""
        if set_kind == "drop":
            context += (
                f"\nThis was DROP SEGMENT {drop_segment or 1} of a drop set — the lighter weight is"
                " intentional and part of the technique. Do NOT treat it as a regression, a failed"
                " set, or a reason to change the working weight. Acknowledge the effort and say"
                " whether to drop again or rack it."
            )
        elif set_kind == "warmup":
            context += (
                "\nThis was a WARM-UP set. It does not count toward the prescribed sets and is"
                " meant to be easy. Do NOT comment on the weight being low or suggest changes."
            )
        elif workout_complete:
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
            base_url, model = _resolve_workout_llm()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": model,
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
                        feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds, set_kind, drop_segment)
                else:
                    logger.warning(f"[WorkoutCoaching] LLM returned {response.status_code}, using fallback")
                    feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds, set_kind, drop_segment)
        except Exception as e:
            logger.warning(f"[WorkoutCoaching] LLM failed: {e}, using fallback")
            feedback_text = self._fallback_feedback(exercise_name, set_number, total_sets, rpe, workout_complete, is_last_set, next_exercise, rest_seconds, set_kind, drop_segment)

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
        rest_seconds: int,
        set_kind: str = "working",
        drop_segment: Optional[int] = None,
    ) -> str:
        """Simple fallback feedback if LLM is unavailable."""
        # Kind first: the RPE branches below would tell David to add weight
        # after a warm-up, or to drop 5 lbs after a set that was already a
        # deliberate drop (2026-07-27 plan §8).
        if set_kind == "drop":
            return f"Drop {drop_segment or 1} logged. Go again or rack it."
        if set_kind == "warmup":
            return "Warm-up logged — doesn't count toward your sets."
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

    async def _command(
        self, user_id: str, db: Session, kind: str, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run one v2 command on behalf of a legacy endpoint.

        Legacy callers have no client-generated command id, so one is minted
        per request: idempotency is then per-HTTP-request, which is exactly the
        guarantee the phone has today. Watch/v2 callers supply their own.
        """
        from app.services.workout_command_service import workout_command_service
        return await workout_command_service.execute(db, user_id, {
            "command_id": str(uuid.uuid4()),
            "kind": kind,
            "origin_device": "phone",
            "payload": payload or {},
        })

    async def skip_exercise(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Skip the current exercise and move to the next incomplete one.

        The skipped exercise is NOT marked done — it stays incomplete so the user
        can come back to it later (e.g. a machine was busy). Only when every other
        exercise is finished does this report the workout as complete.
        """
        result = await self._command(user_id, db, "skip_exercise")
        return {
            "success": True,
            "skipped_exercise": result.get("skipped_exercise"),
            "next_exercise": result.get("next_exercise"),
            "workout_complete": bool(result.get("workout_complete")),
        }

    async def select_exercise(self, user_id: str, exercise_index: int, db: Session) -> Dict[str, Any]:
        """Jump the active cursor to any exercise so they can be done in any order.

        Set progress for the chosen exercise is recomputed from what's already been
        logged, so returning to a partially-done exercise resumes mid-way.
        """
        result = await self._command(
            user_id, db, "select_exercise", {"exercise_index": exercise_index}
        )
        return {
            "success": True,
            "current_exercise_index": exercise_index,
            "current_set_index": result.get("current_set_index"),
            "exercise": result.get("exercise"),
        }

    async def set_exercise_variant(
        self, user_id: str, exercise_index: int, variant: Optional[str], db: Session
    ) -> Dict[str, Any]:
        """Record the machine/variation used for an exercise.

        The variant becomes the identity used for logging + suggestions, so e.g.
        hack-squat weights don't get logged against (and tank) your barbell squat.
        """
        result = await self._command(
            user_id, db, "set_variant", {"exercise_index": exercise_index, "variant": variant}
        )
        return {
            "success": True,
            "exercise_index": exercise_index,
            "variant": result.get("variant"),
            "effective_name": result.get("effective_name"),
            "suggested_weight": result.get("approved_weight"),
            "last_session": result.get("last_session"),
        }

    async def start_rest_timer(
        self,
        user_id: str,
        duration_seconds: int,
        db: Session
    ) -> Dict[str, Any]:
        """Start a rest timer for the current session."""
        result = await self._command(
            user_id, db, "rest_start", {"duration_seconds": duration_seconds}
        )
        return {
            "success": True,
            "duration_seconds": result.get("duration_seconds", duration_seconds),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

    async def stop_rest_timer(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Cancel the rest timer for the current session."""
        await self._command(user_id, db, "rest_stop")
        return {"success": True, "message": "Rest timer stopped"}

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

    async def complete_workout(
        self, user_id: str, db: Session, healthkit_workout_uuid: Optional[str] = None
    ) -> Dict[str, Any]:
        """Complete the active workout and return summary.

        `healthkit_workout_uuid`, when the Watch has already finalized its
        HealthKit workout, binds that exact record to this session instead of
        relying on the same-day heuristic (§4.5, §6.4).
        """
        session = await self.get_active_session(user_id, db)
        if not session:
            raise ValueError("No active workout session")
        session_id = session["id"]

        result = await self._command(
            user_id, db, "complete",
            {"healthkit_workout_uuid": healthkit_workout_uuid} if healthkit_workout_uuid else {},
        )
        return {
            "success": True,
            "session_id": session_id,
            "completed_at": result.get("completed_at"),
            "summary": result.get("summary"),
        }

    async def abandon_workout(self, user_id: str, db: Session) -> Dict[str, Any]:
        """Abandon the current workout session.

        An abandoned workout is NOT saved: any sets logged mid-session (which are
        committed to workout_log as they happen) are deleted, along with the empty
        workout shell created at start. Only the active_workout_session row is kept,
        marked 'abandoned', so it no longer counts as active.
        """
        session = await self.get_active_session(user_id, db)
        if not session:
            # Abandoning nothing is not an error — the other device may have
            # already ended the workout (§4.6 broadcast).
            return {"success": True, "message": "No active workout"}
        await self._command(user_id, db, "abandon")
        return {"success": True, "message": "Workout abandoned"}

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

            # Effective targets, so an added set is reflected in what Sara
            # tells David is left (2026-07-27 plan §6.2).
            from app.services.workout_recalc import target_sets_for
            total_sets = sum(target_sets_for(e) for e in exercises) or snapshot.get("total_sets", 0)
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
                set_line = f"- **Set**: {current_set_idx + 1} of {current_ex['sets']}"
                prescribed = current_ex.get("prescribed_sets")
                if prescribed is not None and prescribed != current_ex["sets"]:
                    # Say when the number differs from the program, so Sara
                    # never presents an in-session addition as the plan (§4.3).
                    set_line += f" ({prescribed} prescribed, adjusted for today only)"
                lines.append(set_line)
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
            live_sets = [s for s in sets_logged if not s.get("voided")]
            if live_sets:
                last_set = live_sets[-1]
                # Label the kind. Without it Sara reads a 95 lb drop segment
                # after a 135 lb working set as a regression and says so (§8).
                kind = last_set.get("set_kind") or "working"
                label = {
                    "drop": f"Drop segment {last_set.get('group_sequence') or 1} (intentionally lighter)",
                    "warmup": "Warm-up (doesn't count toward sets)",
                }.get(kind, "Last Set Logged")
                lines.append("")
                lines.append(f"### {label}: {last_set['exercise_id']} - {last_set['weight']}lbs x {last_set['reps']}" +
                           (f" @ RPE {last_set['rpe']}" if last_set.get('rpe') else ""))
                voided = [s for s in sets_logged if s.get("voided")]
                if voided:
                    lines.append(f"- {len(voided)} set(s) undone this workout — they count toward nothing.")

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
                    lines.append(f"{i}. {ex['name']} ({target_sets_for(ex)} sets)")

            return "\n".join(lines)

        except Exception as e:
            logger.exception(f"Failed to generate workout context: {e}")
            return None


# Singleton instance
workout_session_service = WorkoutSessionService()
