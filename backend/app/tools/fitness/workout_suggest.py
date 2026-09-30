"""
Workout Suggestion Tool

Provides intelligent workout suggestions based on:
- Day of week and scheduled templates
- Past performance (last 2-3 sessions of same workout)
- Progressive overload rules
- Recovery considerations (days since last workout)
- Current training phase goals

This is the KEY tool that makes Sara an intelligent fitness coach.
"""

import json
import logging
from datetime import datetime, timedelta, date
from app.core.timezone import naive_local_now
from typing import Optional, Dict, List
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class WorkoutSuggestTool(BaseTool):
    name = "workout_suggest"
    description = """Suggest today's workout based on training templates, past performance, and progressive overload rules.

    This tool analyzes:
    1. What templates are scheduled for today
    2. Past performance on those templates (last 2-3 sessions)
    3. Progressive overload rules for each exercise
    4. Recovery metrics (days since last workout)
    5. Current phase goals

    Returns a detailed workout prescription with specific weights, sets, reps, and RPE targets.

    Use this when the user asks "what should I do today?", "what's today's workout?", or similar questions about their training."""

    parameters = {
        "type": "object",
        "properties": {
            "target_date": {
                "type": "string",
                "description": "Optional date in YYYY-MM-DD format. Defaults to today if not provided."
            },
            "session": {
                "type": "string",
                "enum": ["am", "pm"],
                "description": "Optional. On a two-a-day, limit the answer to the morning "
                               "strength session or the afternoon hypertrophy session. "
                               "Omit to get both, in order."
            }
        },
        "required": []
    }

    async def execute(self, user_id: str, target_date: Optional[str] = None,
                      session: Optional[str] = None, db: Session = None, **kwargs) -> ToolResult:
        """
        Suggest today's workout

        Args:
            user_id: User ID
            target_date: Optional date (YYYY-MM-DD), defaults to today
            session: Optional "am"/"pm" filter for two-a-day training days
            db: Database session

        Returns:
            ToolResult with workout suggestion including:
            - Every session scheduled for the day, in plan order (`sessions`)
            - Exercise prescriptions with weights/reps/RPE
            - Progressive overload recommendations
            - Recovery notes
        """
        # Get db session if not provided
        if db is None:
            db = get_fitness_db()

        try:
            # Parse target date
            if target_date:
                workout_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            else:
                workout_date = naive_local_now().date()

            day_of_week = workout_date.strftime("%A").lower()

            # 1. Resolve the dated phase of the approved active program.
            from app.services.phase_resolution import get_effective_phase
            active_phase = get_effective_phase(db, user_id, workout_date)
            active_phase_id = active_phase["id"] if active_phase else None

            # 2. Find templates scheduled for this day
            templates_result = db.execute(text("""
                SELECT id, name, phase_id, scheduled_days, exercises, notes, order_in_phase
                FROM fitness_template
                WHERE user_id = :user_id
            """), {"user_id": user_id}).fetchall()

            # Separate into active phase templates and standalone templates
            active_phase_templates = []
            standalone_templates = []

            for row in templates_result:
                template = dict(row._mapping)
                scheduled_days = json.loads(template.get("scheduled_days", "[]"))
                if day_of_week in [d.lower() for d in scheduled_days]:
                    template["scheduled_days"] = scheduled_days
                    template["exercises"] = json.loads(template.get("exercises", "[]"))

                    # Prioritize active phase templates
                    if active_phase_id and template.get("phase_id") == active_phase_id:
                        active_phase_templates.append(template)
                    elif not template.get("phase_id"):
                        # Standalone templates (not linked to any phase)
                        standalone_templates.append(template)
                    # Skip templates from inactive phases

            # Active phase templates first, then standalone
            matching_templates = active_phase_templates + standalone_templates

            if not matching_templates:
                return ToolResult(
                    success=True,
                    data={
                        "day_of_week": day_of_week,
                        "date": str(workout_date),
                        "message": f"No workout template scheduled for {day_of_week}. Consider it a rest day or create a template for this day.",
                        "suggestion": "rest_day"
                    },
                    message=f"No workout scheduled for {day_of_week}"
                )

            # Order the day's sessions the way the plan does (AM before PM);
            # taking [0] used to hide the second session of a two-a-day.
            matching_templates.sort(key=lambda t: (t.get("order_in_phase") is None,
                                                   t.get("order_in_phase") or 0))
            if session:
                wanted = session.strip().lower()
                filtered = [t for t in matching_templates
                            if f" {wanted} " in f" {(t.get('name') or '').lower()} "
                            or f"{wanted} —" in (t.get("name") or "").lower()]
                if filtered:
                    matching_templates = filtered

            # 2. Get phase context if the templates are linked to a phase
            phase_context = None
            phase_for_context = next((t["phase_id"] for t in matching_templates if t.get("phase_id")), None)
            if phase_for_context:
                phase_result = db.execute(text("""
                    SELECT name, goal, status FROM fitness_phase WHERE id = :phase_id
                """), {"phase_id": phase_for_context}).fetchone()
                if phase_result:
                    phase_context = dict(phase_result._mapping)

            from app.services.workout_prescription import prescription_for_week, program_week
            week = program_week(db, user_id, workout_date)

            # 3. Analyze past performance for each exercise in each session
            sessions = []
            for template in matching_templates:
                exercise_suggestions = [
                    self._suggest_for_exercise(db, user_id, spec, week)
                    for spec in template["exercises"]
                ]
                sessions.append({
                    "template": {
                        "id": template["id"],
                        "name": template["name"],
                        "notes": template.get("notes"),
                    },
                    "exercises": exercise_suggestions,
                })

            # 4. Check recovery status
            last_workout_date = db.execute(text("""
                SELECT MAX(session_date) as last_date
                FROM workout_log
                WHERE user_id = :user_id AND session_date IS NOT NULL
                  AND voided_at IS NULL
            """), {"user_id": user_id}).fetchone()

            days_since_last = None
            recovery_note = ""
            if last_workout_date and last_workout_date.last_date:
                days_since_last = (workout_date - last_workout_date.last_date).days
                if days_since_last == 0:
                    recovery_note = "You already trained today. Consider a rest day or light active recovery."
                elif days_since_last == 1:
                    recovery_note = "Back-to-back training. Monitor fatigue and adjust RPE targets if needed."
                elif days_since_last >= 4:
                    recovery_note = f"{days_since_last} days since last workout. You're well-rested!"
                else:
                    recovery_note = f"{days_since_last} days rest. Good recovery time."

            # 5. Compile final suggestion
            session_names = [s["template"]["name"] for s in sessions]
            total_exercises = sum(len(s["exercises"]) for s in sessions)
            if len(sessions) > 1:
                general = (f"Today has {len(sessions)} sessions: {' then '.join(session_names)}. "
                           f"{total_exercises} exercises in total, in that order.")
            else:
                general = (f"Today's workout: {session_names[0]}. "
                           f"Complete {total_exercises} exercises as prescribed.")

            suggestion = {
                "date": str(workout_date),
                "day_of_week": day_of_week,
                "sessions": sessions,
                # Back-compat: existing callers read `template`/`exercises` and
                # get the first session, which is the one that happens first.
                "template": sessions[0]["template"],
                "exercises": sessions[0]["exercises"],
                "phase": phase_context,
                "recovery": {
                    "days_since_last_workout": days_since_last,
                    "note": recovery_note
                },
                "general_notes": general,
            }

            return ToolResult(
                success=True,
                data=suggestion,
                message=f"Workout suggestion for {day_of_week}: {' · '.join(session_names)}"
            )

        except Exception as e:
            logger.exception(f"workout_suggest failed ({type(e).__name__}): {e}")
            return ToolResult(
                success=False,
                error=f"Failed to suggest workout: {str(e)}"
            )

    def _suggest_for_exercise(self, db: Session, user_id: str, exercise_spec: Dict,
                              week: Optional[int] = None) -> Dict:
        """Prescription for one exercise: the plan's number when it has one,
        otherwise progressive overload off the log."""
        from app.services.workout_prescription import prescription_for_week
        from app.services.set_plan import is_plan_driven, resolve_set_plan

        exercise_name = exercise_spec.get("name")
        target_sets = exercise_spec.get("sets", 3)
        target_reps = exercise_spec.get("reps", "8-10")
        target_rpe = exercise_spec.get("rpe_target", 7)

        # Get last 3 sessions of this exercise
        # Note: workout_log uses exercise_id which stores exercise names as strings
        past_sessions = db.execute(text("""
            SELECT session_date, weight, reps, rpe, notes
            FROM workout_log
            WHERE user_id = :user_id
              AND LOWER(exercise_id) = LOWER(:exercise_name)
              AND session_date IS NOT NULL
              AND voided_at IS NULL
              AND COALESCE(set_kind, 'working') = 'working'
            ORDER BY session_date DESC, created_at DESC
            LIMIT 15
        """), {
            "user_id": user_id,
            "exercise_name": exercise_name
        }).fetchall()

        # Group by session date
        sessions_by_date = {}
        for log in past_sessions:
            log_date = log.session_date
            if log_date not in sessions_by_date:
                sessions_by_date[log_date] = []
            sessions_by_date[log_date].append({
                "weight": log.weight,
                "reps": log.reps,
                "rpe": log.rpe or 7,
                "notes": log.notes
            })

        suggested_weight = None
        progression_note = ""

        # The AM lifts carry a structured top/backoff loading table (A1/A2) —
        # or, for exercises that predate it, the same table as text in
        # `notes`. Where the plan states this week's load, it is the
        # prescription — a +5/+10 extrapolation from the log would quietly
        # compete with the program.
        resolved_plan = None
        if is_plan_driven(exercise_spec) and week:
            resolved_plan = resolve_set_plan(exercise_spec, week, last_top_set=None)
        if resolved_plan and resolved_plan["sets"]:
            top_entry = next(s for s in resolved_plan["sets"] if s["kind"] == "top")
            backoff_entries = [s for s in resolved_plan["sets"] if s["kind"] == "backoff"]
            prescribed = {"top": f"{top_entry['weight']}x{top_entry['reps']}"}
            if backoff_entries:
                b = backoff_entries[0]
                prescribed["backoff"] = f"{b['weight']}x{b['reps']} x{len(backoff_entries)}"
        else:
            prescribed = prescription_for_week(exercise_spec.get("notes") or "", week)

        if sessions_by_date:
            last_date = max(sessions_by_date.keys())
            last_session = sessions_by_date[last_date]

            # Simple progressive overload logic:
            # If all sets completed with RPE < 8, suggest adding weight
            # If struggled (any RPE >= 9), maintain weight
            # Default: 5lb increase for upper body, 10lb for lower body

            last_weights = [s["weight"] for s in last_session]
            last_reps = [s["reps"] for s in last_session]
            last_rpes = [s["rpe"] for s in last_session]

            avg_weight = sum(last_weights) / len(last_weights) if last_weights else 0
            avg_rpe = sum(last_rpes) / len(last_rpes) if last_rpes else 7

            # Check if user is using consistent reps
            if last_reps:
                min_reps = min(last_reps)

                # Progressive overload decision tree
                if avg_rpe < 7.5 and min_reps >= int(target_reps.split("-")[0] if "-" in str(target_reps) else target_reps):
                    # Easy session, all reps hit - add weight
                    # Heuristic: add 5lbs for upper body, 10lbs for lower body
                    is_lower_body = any(keyword in exercise_name.lower() for keyword in ["squat", "deadlift", "leg", "lunge"])
                    weight_increase = 10 if is_lower_body else 5
                    suggested_weight = avg_weight + weight_increase
                    progression_note = f"Last session felt easy (RPE {avg_rpe:.1f}). Adding {weight_increase}lbs."
                elif avg_rpe >= 8.5:
                    # Hard session - maintain weight or reduce slightly
                    suggested_weight = avg_weight
                    progression_note = f"Last session was challenging (RPE {avg_rpe:.1f}). Maintaining weight."
                elif min_reps < int(target_reps.split("-")[0] if "-" in str(target_reps) else target_reps):
                    # Didn't hit rep target - maintain weight
                    suggested_weight = avg_weight
                    progression_note = f"Didn't complete all reps last time. Focus on hitting {target_reps} reps."
                else:
                    # Normal progression
                    suggested_weight = avg_weight + 2.5  # Small increment
                    progression_note = f"Solid session. Small progression from {avg_weight}lbs."
            else:
                suggested_weight = avg_weight
        else:
            # No history - suggest starting conservative
            progression_note = "First time doing this exercise. Start with a weight that feels like RPE 7."
            suggested_weight = None  # User needs to choose

        suggestion = {
            "exercise": exercise_name,
            "sets": target_sets,
            "reps": target_reps,
            "rpe_target": target_rpe,
            "suggested_weight": suggested_weight,
            "progression_note": progression_note,
            "last_session_summary": f"{len(sessions_by_date)} previous sessions found" if sessions_by_date else "No previous history"
        }

        if prescribed.get("top"):
            suggestion["prescribed_top_set"] = prescribed["top"]
            if prescribed.get("backoff"):
                suggestion["prescribed_backoff"] = prescribed["backoff"]
            week_label = f" (week {week})" if week else ""
            suggestion["progression_note"] = (
                f"The program prescribes{week_label}: top set {prescribed['top']}"
                + (f", backoffs at {prescribed['backoff']}" if prescribed.get("backoff") else "")
                + ". Follow the plan, not a computed increment."
            )
            # Don't offer a competing number.
            suggestion["suggested_weight"] = None

        return suggestion
