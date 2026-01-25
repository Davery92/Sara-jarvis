"""
Karma system services for Sara's cognitive architecture.

The karma system gives Sara and her sub-agents persistent internal stakes
through multi-dimensional performance tracking.
"""

from .service import KarmaService, KarmaEvent, get_karma_service
from .feedback import (
    FeedbackCollector,
    FeedbackSignal,
    FeedbackType,
    record_user_feedback,
    record_correction,
    record_task_outcome,
    record_proactive_feedback,
    record_consolidation_quality,
    record_reflection_audit,
)

__all__ = [
    "KarmaService",
    "KarmaEvent",
    "get_karma_service",
    "FeedbackCollector",
    "FeedbackSignal",
    "FeedbackType",
    "record_user_feedback",
    "record_correction",
    "record_task_outcome",
    "record_proactive_feedback",
    "record_consolidation_quality",
    "record_reflection_audit",
]
