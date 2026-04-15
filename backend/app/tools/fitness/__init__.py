"""
Fitness Tools Module
Tools for fitness tracking: notes, food logging, workout logging, recovery tracking,
templates, programs, phases, and training schedule management.
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
    WorkoutDetailsTool,
    WorkoutStatsTool
)
from app.tools.fitness.recovery_log import (
    RecoveryLogCreateTool,
    RecoveryLogGetTool,
    RecoveryLogRecentTool
)
from app.tools.fitness.template_tools import (
    TemplateListTool,
    TemplateGetTool,
    TemplateUpdateTool
)
from app.tools.fitness.program_tools import (
    ProgramListTool,
    ProgramGetTool,
    PhaseListTool,
    PhaseGetTool,
    PhaseUpdateTool,
    PhaseActivateTool
)
from app.tools.fitness.training_schedule import TrainingScheduleTool

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
    "WorkoutDetailsTool",
    "WorkoutStatsTool",
    # Recovery Log
    "RecoveryLogCreateTool",
    "RecoveryLogGetTool",
    "RecoveryLogRecentTool",
    # Templates
    "TemplateListTool",
    "TemplateGetTool",
    "TemplateUpdateTool",
    # Programs & Phases
    "ProgramListTool",
    "ProgramGetTool",
    "PhaseListTool",
    "PhaseGetTool",
    "PhaseUpdateTool",
    "PhaseActivateTool",
    # Training Schedule
    "TrainingScheduleTool",
]
