"""
Fitness Tools Module
Tools for fitness tracking: notes, food logging, workout logging, templates, and intelligent workout suggestions
"""
from app.tools.fitness.fitness_notes import (
    FitnessNoteCreateTool,
    FitnessNoteSearchTool,
    FitnessNoteEditTool
)
from app.tools.fitness.food_log import (
    FoodLogCreateTool,
    FoodLogSearchTool,
    FoodLogSummaryTool
)
from app.tools.fitness.workout_log import (
    WorkoutListTool,
    WorkoutLogCreateTool,
    WorkoutStatsTool
)
from app.tools.fitness.template_tools import (
    TemplateListTool,
    TemplateGetTool
)

__all__ = [
    # Fitness Notes
    "FitnessNoteCreateTool",
    "FitnessNoteSearchTool",
    "FitnessNoteEditTool",
    # Food Log
    "FoodLogCreateTool",
    "FoodLogSearchTool",
    "FoodLogSummaryTool",
    # Workout Log
    "WorkoutListTool",
    "WorkoutLogCreateTool",
    "WorkoutStatsTool",
    # Templates
    "TemplateListTool",
    "TemplateGetTool",
]
