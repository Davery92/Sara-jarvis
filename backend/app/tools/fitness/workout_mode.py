"""
Workout Mode Tool - Conversational set logging during active workouts

Allows Sara to log sets via natural language when user is in active workout mode.
Supports:
- "done" / "finished" -> Log with expected values from snapshot
- "done, felt light" -> Log RPE 6-7, suggest weight increase
- "done, felt heavy" -> Log RPE 8-9, maintain weight
- "135 x 8" -> Parse as explicit weight x reps
- "skip" -> Skip current exercise
"""

from typing import Dict, Any, Optional, Literal
import logging
from sqlalchemy.orm import Session

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WorkoutModeLogTool(BaseTool):
    """Log sets or skip exercises during an active workout session via natural language"""

    name = "workout_mode_log"
    description = """Use this tool when the user is in an active workout session and says things like:
    - "done" / "finished" / "completed" -> Log the current set with expected values
    - "done, felt light/easy" -> Log with lower RPE (6-7), suggest weight increase next set
    - "done, felt heavy/hard" -> Log with higher RPE (8-9), maintain or reduce weight
    - "done but failed" -> Log as failed set, suggest weight reduction
    - "135 x 8" or "185 for 6" -> Parse explicit weight and reps
    - "skip" / "skip this exercise" -> Move to next exercise
    - "rest" or "start rest timer" -> Start the rest timer

    Only use this tool if the user has an active workout session.
    Returns coaching feedback and next set information."""

    # Define schema for Gemini function calling
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["log_set", "skip_exercise", "start_rest"],
                "description": "Action to perform: log a set, skip exercise, or start rest timer"
            },
            "weight": {
                "type": "number",
                "description": "Weight used for the set in lbs. Optional - if not provided, uses suggested weight from workout snapshot."
            },
            "reps": {
                "type": "integer",
                "description": "Number of reps completed. Optional - if not provided, uses target reps from workout snapshot."
            },
            "rpe": {
                "type": "integer",
                "description": "Rate of Perceived Exertion (1-10). Optional - can be inferred from rpe_feeling."
            },
            "rpe_feeling": {
                "type": "string",
                "enum": ["light", "moderate", "hard", "failed"],
                "description": "How the set felt. Used to infer RPE if not explicitly provided."
            },
            "notes": {
                "type": "string",
                "description": "Optional notes about the set (form cues, adjustments, etc.)"
            },
            "rest_duration": {
                "type": "integer",
                "description": "Rest timer duration in seconds. Default is 120 for compounds, 60 for isolation."
            }
        },
        "required": ["action"]
    }

    async def execute(
        self,
        action: Literal["log_set", "skip_exercise", "start_rest"],
        weight: Optional[float] = None,
        reps: Optional[int] = None,
        rpe: Optional[int] = None,
        rpe_feeling: Optional[str] = None,
        notes: Optional[str] = None,
        rest_duration: Optional[int] = None,
        user_id: str = None,
        db: Session = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute the workout mode action"""

        from app.services.workout_session_service import workout_session_service

        if not user_id or not db:
            return {
                "success": False,
                "error": "Missing user_id or database session"
            }

        try:
            # Check for active session first
            session = await workout_session_service.get_active_session(user_id, db)
            if not session:
                return {
                    "success": False,
                    "error": "No active workout session. Start a workout first!",
                    "message_for_user": "You don't have an active workout right now. Would you like to start one?"
                }

            if action == "log_set":
                result = await workout_session_service.log_set(
                    user_id=user_id,
                    weight=weight,
                    reps=reps,
                    rpe=rpe,
                    rpe_feeling=rpe_feeling,
                    notes=notes,
                    db=db
                )

                # Format coaching feedback
                feedback = result.get("coaching_feedback", "Set logged!")
                next_set = result.get("next_set")

                if next_set:
                    if next_set.get("workout_complete"):
                        feedback += f"\n\nWorkout complete! Great session - {result.get('total_sets_completed', 0)} sets done."
                    elif next_set.get("exercise_complete"):
                        feedback += f"\n\nExercise complete! Up next: {next_set.get('next_exercise', 'Unknown')}"
                    else:
                        feedback += f"\n\nNext: Set {next_set.get('set_number', '?')} of {next_set.get('exercise', 'current exercise')}"

                return {
                    "success": True,
                    "action": "set_logged",
                    "logged": result.get("logged", {}),
                    "coaching_feedback": feedback,
                    "next_set": next_set,
                    "session_progress": {
                        "total_sets": result.get("total_sets_completed", 0),
                        "total_volume": result.get("total_volume", 0)
                    }
                }

            elif action == "skip_exercise":
                result = await workout_session_service.skip_exercise(user_id, db)

                return {
                    "success": True,
                    "action": "exercise_skipped",
                    "skipped_exercise": result.get("skipped_exercise"),
                    "next_exercise": result.get("next_exercise"),
                    "message_for_user": f"Skipped {result.get('skipped_exercise', 'exercise')}. Moving to {result.get('next_exercise', 'next exercise')}."
                }

            elif action == "start_rest":
                # Determine default rest duration based on current exercise type
                if rest_duration is None:
                    # Get current exercise from snapshot to determine rest time
                    snapshot = session.get("workout_snapshot", {})
                    exercises = snapshot.get("exercises", [])
                    current_idx = session.get("current_exercise_index", 0)

                    if current_idx < len(exercises):
                        current_exercise = exercises[current_idx]
                        exercise_name = current_exercise.get("name", "").lower()

                        # Compound exercises get longer rest
                        compound_keywords = ["squat", "deadlift", "bench", "press", "row", "pull"]
                        is_compound = any(kw in exercise_name for kw in compound_keywords)
                        rest_duration = 180 if is_compound else 90
                    else:
                        rest_duration = 120

                result = await workout_session_service.start_rest_timer(
                    user_id=user_id,
                    duration_seconds=rest_duration,
                    db=db
                )

                minutes = rest_duration // 60
                seconds = rest_duration % 60
                time_str = f"{minutes}:{seconds:02d}" if minutes else f"{seconds}s"

                return {
                    "success": True,
                    "action": "rest_started",
                    "duration_seconds": rest_duration,
                    "message_for_user": f"Rest timer started: {time_str}"
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }

        except Exception as e:
            logger.error(f"Workout mode tool error: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class WorkoutModeStartTool(BaseTool):
    """Start a new workout session from a template"""

    name = "start_workout"
    description = """Use this tool when the user wants to start a workout.
    They might say:
    - "start my workout" / "begin workout"
    - "let's do Push Day"
    - "start my upper body workout"
    - "I'm ready to train"

    If the user doesn't specify a template, you should ask which workout they want to do,
    or suggest one based on their schedule/history."""

    parameters = {
        "type": "object",
        "properties": {
            "template_id": {
                "type": "string",
                "description": "The ID of the workout template to start"
            },
            "template_name": {
                "type": "string",
                "description": "The name of the workout template (used to find the template if ID not provided)"
            }
        },
        "required": []
    }

    async def execute(
        self,
        template_id: Optional[str] = None,
        template_name: Optional[str] = None,
        user_id: str = None,
        db: Session = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Start a workout session"""

        from app.services.workout_session_service import workout_session_service
        from sqlalchemy import text

        if not user_id or not db:
            return {
                "success": False,
                "error": "Missing user_id or database session"
            }

        try:
            # If template_name provided but not ID, look it up
            if not template_id and template_name:
                query = text("""
                    SELECT id, name FROM fitness_template
                    WHERE user_id = :user_id
                    AND LOWER(name) LIKE LOWER(:name)
                    LIMIT 1
                """)
                result = db.execute(query, {
                    "user_id": user_id,
                    "name": f"%{template_name}%"
                }).fetchone()

                if result:
                    template_id = result.id
                else:
                    # List available templates
                    templates_query = text("""
                        SELECT id, name FROM fitness_template
                        WHERE user_id = :user_id
                        ORDER BY last_used_at DESC NULLS LAST
                        LIMIT 10
                    """)
                    templates = db.execute(templates_query, {"user_id": user_id}).fetchall()

                    template_list = [{"id": t.id, "name": t.name} for t in templates]

                    return {
                        "success": False,
                        "error": f"No template found matching '{template_name}'",
                        "available_templates": template_list,
                        "message_for_user": f"I couldn't find a template called '{template_name}'. Here are your available workouts - which one would you like to start?"
                    }

            if not template_id:
                # No template specified - list available ones
                templates_query = text("""
                    SELECT id, name FROM fitness_template
                    WHERE user_id = :user_id
                    ORDER BY last_used_at DESC NULLS LAST
                    LIMIT 10
                """)
                templates = db.execute(templates_query, {"user_id": user_id}).fetchall()

                template_list = [{"id": t.id, "name": t.name} for t in templates]

                return {
                    "success": False,
                    "error": "No template specified",
                    "available_templates": template_list,
                    "message_for_user": "Which workout would you like to start today?"
                }

            # Start the workout
            result = await workout_session_service.start_workout(
                user_id=user_id,
                template_id=template_id,
                db=db
            )

            session = result.get("session", {})
            snapshot = session.get("workout_snapshot", {})
            exercises = snapshot.get("exercises", [])

            # Build a summary of the workout
            exercise_summary = []
            for i, ex in enumerate(exercises[:5]):  # Show first 5 exercises
                exercise_summary.append(f"  {i+1}. {ex.get('name')} - {ex.get('sets')} x {ex.get('reps')}")

            if len(exercises) > 5:
                exercise_summary.append(f"  ... and {len(exercises) - 5} more exercises")

            return {
                "success": True,
                "action": "workout_started",
                "session_id": session.get("id"),
                "template_name": snapshot.get("template_name"),
                "exercises": exercises,
                "first_exercise": exercises[0] if exercises else None,
                "message_for_user": f"Started {snapshot.get('template_name', 'your workout')}! Here's the plan:\n" +
                    "\n".join(exercise_summary) +
                    f"\n\nFirst up: {exercises[0].get('name') if exercises else 'Unknown'}" +
                    f"\nSuggested weight: {exercises[0].get('suggested_weight', 'TBD')} lbs" if exercises else ""
            }

        except Exception as e:
            logger.error(f"Start workout tool error: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class WorkoutModeCompleteTool(BaseTool):
    """Complete or abandon the current workout session"""

    name = "end_workout"
    description = """Use this tool when the user wants to finish their workout.
    They might say:
    - "done with workout" / "finished training"
    - "end workout" / "complete session"
    - "quit workout" / "cancel workout" (abandons without completing)"""

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["complete", "abandon"],
                "description": "Whether to complete the workout (success) or abandon it (quit early)"
            }
        },
        "required": ["action"]
    }

    async def execute(
        self,
        action: Literal["complete", "abandon"],
        user_id: str = None,
        db: Session = None,
        **kwargs
    ) -> Dict[str, Any]:
        """End the workout session"""

        from app.services.workout_session_service import workout_session_service

        if not user_id or not db:
            return {
                "success": False,
                "error": "Missing user_id or database session"
            }

        try:
            if action == "complete":
                result = await workout_session_service.complete_workout(user_id, db)

                summary = result.get("summary", {})
                duration_min = summary.get("duration_minutes", 0)

                return {
                    "success": True,
                    "action": "workout_completed",
                    "summary": summary,
                    "message_for_user": (
                        f"Great workout! Here's your summary:\n"
                        f"  Duration: {duration_min} minutes\n"
                        f"  Sets completed: {summary.get('total_sets', 0)}\n"
                        f"  Total volume: {summary.get('total_volume', 0):,.0f} lbs\n"
                        f"  Exercises: {summary.get('exercises_completed', 0)}"
                    )
                }

            elif action == "abandon":
                result = await workout_session_service.abandon_workout(user_id, db)

                return {
                    "success": True,
                    "action": "workout_abandoned",
                    "message_for_user": "Workout ended. No worries - we'll pick up where you left off next time!"
                }

        except Exception as e:
            logger.error(f"End workout tool error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
