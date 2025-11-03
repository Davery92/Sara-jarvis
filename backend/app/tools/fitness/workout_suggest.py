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
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..base import BaseTool, ToolResult


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

    async def execute(self, user_id: str, target_date: Optional[str] = None, db: Session = None, **kwargs) -> ToolResult:
        """
        Suggest today's workout

        Args:
            user_id: User ID
            target_date: Optional date (YYYY-MM-DD), defaults to today
            db: Database session

        Returns:
            ToolResult with workout suggestion including:
            - Template details
            - Exercise prescriptions with weights/reps/RPE
            - Progressive overload recommendations
            - Recovery notes
        """
        try:
            # Parse target date
            if target_date:
                workout_date = datetime.strptime(target_date, "%Y-%m-%d").date()
            else:
                workout_date = datetime.now().date()

            day_of_week = workout_date.strftime("%A").lower()

            # 1. Find templates scheduled for this day
            templates_result = db.execute(text("""
                SELECT id, name, phase_id, scheduled_days, exercises, notes
                FROM fitness_template
                WHERE user_id = :user_id
            """), {"user_id": user_id}).fetchall()

            matching_templates = []
            for row in templates_result:
                template = dict(row._mapping)
                scheduled_days = json.loads(template.get("scheduled_days", "[]"))
                if day_of_week in [d.lower() for d in scheduled_days]:
                    template["scheduled_days"] = scheduled_days
                    template["exercises"] = json.loads(template.get("exercises", "[]"))
                    matching_templates.append(template)

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

            # Use the first matching template (if multiple, user can specify)
            template = matching_templates[0]

            # 2. Get phase context if template is linked to a phase
            phase_context = None
            if template.get("phase_id"):
                phase_result = db.execute(text("""
                    SELECT name, goal, status FROM fitness_phase WHERE id = :phase_id
                """), {"phase_id": template["phase_id"]}).fetchone()
                if phase_result:
                    phase_context = dict(phase_result._mapping)

            # 3. Analyze past performance for each exercise in the template
            exercise_suggestions = []

            for exercise_spec in template["exercises"]:
                exercise_name = exercise_spec.get("name")
                target_sets = exercise_spec.get("sets", 3)
                target_reps = exercise_spec.get("reps", "8-10")
                target_rpe = exercise_spec.get("rpe_target", 7)

                # Get last 3 sessions of this exercise
                past_sessions = db.execute(text("""
                    SELECT session_date, weight, reps, rpe, notes
                    FROM workout_log
                    WHERE user_id = :user_id
                      AND (exercise_name = :exercise_name OR exercise_id = :exercise_name)
                      AND session_date IS NOT NULL
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

                # Analyze last session
                last_session = None
                suggested_weight = None
                suggested_reps = target_reps
                progression_note = ""

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
                        avg_reps = sum(last_reps) / len(last_reps)
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

                exercise_suggestion = {
                    "exercise": exercise_name,
                    "sets": target_sets,
                    "reps": target_reps,
                    "rpe_target": target_rpe,
                    "suggested_weight": suggested_weight,
                    "progression_note": progression_note,
                    "last_session_summary": f"{len(sessions_by_date)} previous sessions found" if sessions_by_date else "No previous history"
                }

                exercise_suggestions.append(exercise_suggestion)

            # 4. Check recovery status
            last_workout_date = db.execute(text("""
                SELECT MAX(session_date) as last_date
                FROM workout_log
                WHERE user_id = :user_id AND session_date IS NOT NULL
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
            suggestion = {
                "date": str(workout_date),
                "day_of_week": day_of_week,
                "template": {
                    "id": template["id"],
                    "name": template["name"],
                    "notes": template.get("notes")
                },
                "phase": phase_context,
                "exercises": exercise_suggestions,
                "recovery": {
                    "days_since_last_workout": days_since_last,
                    "note": recovery_note
                },
                "general_notes": f"Today's workout: {template['name']}. Complete {len(exercise_suggestions)} exercises as prescribed."
            }

            return ToolResult(
                success=True,
                data=suggestion,
                message=f"Workout suggestion for {day_of_week}: {template['name']}"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to suggest workout: {str(e)}"
            )
