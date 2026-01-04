"""
Daily Brief System
A four-layer contextual memory system that provides Sara with
a continuously-updated understanding of David.

Layers:
- Moment: Real-time conversation state (no LLM)
- Day: Daily conversation accumulation (20B model)
- Context: Active threads, predictions, questions (20B model)
- Stable: Deep understanding of David (120B model, weekly)
"""
from .brief_service import DailyBriefService, daily_brief_service
from .moment_layer import MomentLayer, moment_layer
from .day_layer import DayLayer, day_layer
from .context_layer import ContextLayer, context_layer
from .stable_layer import StableLayer, stable_layer
from .compiler import BriefCompiler, brief_compiler
from .archiver import Archiver, archiver
from .scheduler import DailyBriefScheduler, daily_brief_scheduler

__all__ = [
    # Main service
    "DailyBriefService",
    "daily_brief_service",
    # Layers
    "MomentLayer",
    "moment_layer",
    "DayLayer",
    "day_layer",
    "ContextLayer",
    "context_layer",
    "StableLayer",
    "stable_layer",
    # Utilities
    "BriefCompiler",
    "brief_compiler",
    "Archiver",
    "archiver",
    # Scheduler
    "DailyBriefScheduler",
    "daily_brief_scheduler",
]
