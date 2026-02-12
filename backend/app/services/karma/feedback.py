"""
Karma Feedback Collection System.

Collects and processes feedback signals that affect agent karma:
- Explicit user feedback (ratings, thumbs up/down)
- Implicit signals (corrections, task completion, timing)
- System-generated feedback (reflection audits, validation)
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .service import KarmaService, KarmaEvent, get_karma_service

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    """Types of feedback that can be collected."""
    # Explicit user feedback
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"  # 1-5 scale
    CORRECTION = "correction"  # User corrected Sara's response

    # Task-based feedback
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_ABANDONED = "task_abandoned"

    # Timing feedback
    RESPONSE_TIMING = "response_timing"  # Was response timely?
    PROACTIVE_HIT = "proactive_hit"  # Proactive action was useful
    PROACTIVE_MISS = "proactive_miss"  # Proactive action was unwanted

    # Implicit feedback (detected from user messages)
    IMPLICIT_POSITIVE = "implicit_positive"  # User showed satisfaction
    IMPLICIT_NEGATIVE = "implicit_negative"  # User showed dissatisfaction

    # Learning feedback (lesson effectiveness)
    LESSON_APPLIED_SUCCESS = "lesson_applied_success"  # Lesson helped
    LESSON_APPLIED_FAILURE = "lesson_applied_failure"  # Lesson didn't help

    # System feedback
    REFLECTION_AUDIT = "reflection_audit"
    CONSOLIDATION_QUALITY = "consolidation_quality"
    ACCURACY_CHECK = "accuracy_check"


@dataclass
class FeedbackSignal:
    """A collected feedback signal."""
    feedback_type: FeedbackType
    agent_id: str
    value: float  # Normalized to -1.0 to 1.0
    context: Optional[Dict[str, Any]] = None
    evidence_id: Optional[str] = None
    evidence_type: Optional[str] = None


# Mapping of feedback types to karma dimensions and delta scaling
FEEDBACK_DIMENSION_MAP = {
    # Sara's dimensions
    FeedbackType.THUMBS_UP: [
        ("sara", "helpfulness", 2.0),
    ],
    FeedbackType.THUMBS_DOWN: [
        ("sara", "helpfulness", -3.0),
    ],
    FeedbackType.RATING: [
        ("sara", "helpfulness", 1.0),  # Scaled by rating value
    ],
    FeedbackType.CORRECTION: [
        ("sara", "accuracy", -2.0),
        ("sara", "calibration", -1.0),  # Should have been more uncertain
    ],
    FeedbackType.TASK_COMPLETED: [
        ("sara", "helpfulness", 1.5),
    ],
    FeedbackType.TASK_FAILED: [
        ("sara", "helpfulness", -2.0),
    ],
    FeedbackType.RESPONSE_TIMING: [
        ("sara", "timing", 2.0),  # Scaled by timing quality
    ],
    FeedbackType.PROACTIVE_HIT: [
        ("sara", "proactivity", 3.0),
        ("sara", "timing", 1.5),
    ],
    FeedbackType.PROACTIVE_MISS: [
        ("sara", "proactivity", -2.0),
    ],

    # Implicit feedback from user messages
    FeedbackType.IMPLICIT_POSITIVE: [
        ("sara", "helpfulness", 1.5),
        ("sara", "accuracy", 1.0),
    ],
    FeedbackType.IMPLICIT_NEGATIVE: [
        ("sara", "helpfulness", -2.0),
        ("sara", "accuracy", -1.5),
    ],

    # Learning effectiveness feedback
    FeedbackType.LESSON_APPLIED_SUCCESS: [
        ("sara", "learning", 2.0),
        ("sara", "helpfulness", 1.0),
    ],
    FeedbackType.LESSON_APPLIED_FAILURE: [
        ("sara", "learning", -1.0),
    ],

    # Consolidation agent dimensions
    FeedbackType.CONSOLIDATION_QUALITY: [
        ("consolidation", "accuracy", 2.0),
        ("consolidation", "compression_quality", 1.5),
    ],

    # Reflection agent dimensions
    FeedbackType.REFLECTION_AUDIT: [
        ("reflection", "insight_quality", 2.0),
        ("reflection", "proposal_acceptance", 1.0),
    ],

    # Accuracy checks affect multiple
    FeedbackType.ACCURACY_CHECK: [
        ("sara", "accuracy", 3.0),
        ("consolidation", "accuracy", 1.5),
    ],
}


class FeedbackCollector:
    """
    Collects and processes feedback signals into karma events.

    Handles:
    - Signal normalization
    - Dimension mapping
    - Delta scaling based on signal strength
    - Batching for efficiency
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._pending_signals: List[FeedbackSignal] = []

    async def collect(self, signal: FeedbackSignal) -> None:
        """
        Collect a feedback signal for processing.

        The signal will be converted to karma events and applied.
        """
        logger.debug(f"Collected feedback: {signal.feedback_type.value} for {signal.agent_id}")
        self._pending_signals.append(signal)

        # Process immediately for now (could batch in future)
        await self._process_pending()

    async def _process_pending(self) -> List[KarmaEvent]:
        """Process all pending feedback signals."""
        if not self._pending_signals:
            return []

        karma_service = await get_karma_service(self.db)
        events_created = []

        for signal in self._pending_signals:
            events = await self._signal_to_events(signal)
            for event in events:
                await karma_service.record_event(event)
                events_created.append(event)

        self._pending_signals = []
        return events_created

    async def _signal_to_events(self, signal: FeedbackSignal) -> List[KarmaEvent]:
        """Convert a feedback signal to karma events."""
        events = []

        mappings = FEEDBACK_DIMENSION_MAP.get(signal.feedback_type, [])

        for agent_id, dimension, base_delta in mappings:
            # Only apply to matching agent or if signal is for that agent
            if signal.agent_id != agent_id and signal.agent_id != "all":
                continue

            # Scale delta by signal value
            scaled_delta = base_delta * signal.value

            # Create reason string
            reason = self._build_reason(signal)

            event = KarmaEvent(
                agent_id=agent_id,
                dimension_name=dimension,
                delta=scaled_delta,
                reason=reason,
                evidence_type=signal.evidence_type or signal.feedback_type.value,
                evidence_ids=[signal.evidence_id] if signal.evidence_id else None
            )
            events.append(event)

        return events

    def _build_reason(self, signal: FeedbackSignal) -> str:
        """Build a human-readable reason for the karma event."""
        reasons = {
            FeedbackType.THUMBS_UP: "User gave positive feedback",
            FeedbackType.THUMBS_DOWN: "User gave negative feedback",
            FeedbackType.RATING: f"User rating: {signal.value * 2.5 + 2.5:.1f}/5",
            FeedbackType.CORRECTION: "User corrected response",
            FeedbackType.TASK_COMPLETED: "Task completed successfully",
            FeedbackType.TASK_FAILED: "Task failed",
            FeedbackType.TASK_ABANDONED: "Task was abandoned",
            FeedbackType.RESPONSE_TIMING: "Response timing feedback",
            FeedbackType.PROACTIVE_HIT: "Proactive action was useful",
            FeedbackType.PROACTIVE_MISS: "Proactive action was not helpful",
            FeedbackType.IMPLICIT_POSITIVE: "User showed implicit satisfaction",
            FeedbackType.IMPLICIT_NEGATIVE: "User showed implicit dissatisfaction",
            FeedbackType.LESSON_APPLIED_SUCCESS: "Applied lesson was effective",
            FeedbackType.LESSON_APPLIED_FAILURE: "Applied lesson was not effective",
            FeedbackType.REFLECTION_AUDIT: "Reflection agent audit",
            FeedbackType.CONSOLIDATION_QUALITY: "Consolidation quality assessment",
            FeedbackType.ACCURACY_CHECK: "Accuracy verification",
        }
        return reasons.get(signal.feedback_type, signal.feedback_type.value)


# Convenience functions for common feedback patterns

async def record_user_feedback(
    db: AsyncSession,
    feedback_type: str,
    value: float,
    message_id: Optional[str] = None,
    context: Optional[Dict] = None
) -> None:
    """
    Record explicit user feedback on a response.

    Args:
        db: Database session
        feedback_type: "thumbs_up", "thumbs_down", or "rating"
        value: For rating, 1-5 scale. For thumbs, ignored.
        message_id: The message being rated
        context: Additional context
    """
    collector = FeedbackCollector(db)

    # Normalize value to -1 to 1
    if feedback_type == "thumbs_up":
        normalized = 1.0
        ftype = FeedbackType.THUMBS_UP
    elif feedback_type == "thumbs_down":
        normalized = 1.0  # Negative delta already in mapping
        ftype = FeedbackType.THUMBS_DOWN
    elif feedback_type == "rating":
        # Convert 1-5 to -1 to 1
        normalized = (value - 3) / 2
        ftype = FeedbackType.RATING
    else:
        logger.warning(f"Unknown feedback type: {feedback_type}")
        return

    signal = FeedbackSignal(
        feedback_type=ftype,
        agent_id="sara",
        value=normalized,
        context=context,
        evidence_id=message_id,
        evidence_type="message"
    )

    await collector.collect(signal)


async def record_correction(
    db: AsyncSession,
    message_id: str,
    original_content: str,
    corrected_content: str
) -> None:
    """Record that user corrected Sara's response."""
    collector = FeedbackCollector(db)

    signal = FeedbackSignal(
        feedback_type=FeedbackType.CORRECTION,
        agent_id="sara",
        value=1.0,
        context={
            "original": original_content[:200],
            "corrected": corrected_content[:200]
        },
        evidence_id=message_id,
        evidence_type="message"
    )

    await collector.collect(signal)


async def record_task_outcome(
    db: AsyncSession,
    task_type: str,
    success: bool,
    task_id: Optional[str] = None,
    context: Optional[Dict] = None
) -> None:
    """Record task completion or failure."""
    collector = FeedbackCollector(db)

    signal = FeedbackSignal(
        feedback_type=FeedbackType.TASK_COMPLETED if success else FeedbackType.TASK_FAILED,
        agent_id="sara",
        value=1.0,
        context={"task_type": task_type, **(context or {})},
        evidence_id=task_id,
        evidence_type="task"
    )

    await collector.collect(signal)


async def record_proactive_feedback(
    db: AsyncSession,
    was_useful: bool,
    action_type: str,
    action_id: Optional[str] = None
) -> None:
    """Record feedback on a proactive action."""
    collector = FeedbackCollector(db)

    signal = FeedbackSignal(
        feedback_type=FeedbackType.PROACTIVE_HIT if was_useful else FeedbackType.PROACTIVE_MISS,
        agent_id="sara",
        value=1.0,
        context={"action_type": action_type},
        evidence_id=action_id,
        evidence_type="proactive_action"
    )

    await collector.collect(signal)


async def record_consolidation_quality(
    db: AsyncSession,
    run_id: str,
    quality_score: float,  # 0-1 scale
    context: Optional[Dict] = None
) -> None:
    """Record consolidation run quality assessment."""
    collector = FeedbackCollector(db)

    # Convert 0-1 to -1 to 1
    normalized = (quality_score - 0.5) * 2

    signal = FeedbackSignal(
        feedback_type=FeedbackType.CONSOLIDATION_QUALITY,
        agent_id="consolidation",
        value=normalized,
        context=context,
        evidence_id=run_id,
        evidence_type="consolidation_run"
    )

    await collector.collect(signal)


async def record_reflection_audit(
    db: AsyncSession,
    audit_id: str,
    proposal_accepted: bool,
    insight_quality: float,  # 0-1 scale
    context: Optional[Dict] = None
) -> None:
    """Record reflection agent audit outcome."""
    collector = FeedbackCollector(db)

    # Insight quality: 0-1 to -1 to 1
    normalized = (insight_quality - 0.5) * 2

    signal = FeedbackSignal(
        feedback_type=FeedbackType.REFLECTION_AUDIT,
        agent_id="reflection",
        value=normalized,
        context={
            "proposal_accepted": proposal_accepted,
            **(context or {})
        },
        evidence_id=audit_id,
        evidence_type="reflection_audit"
    )

    await collector.collect(signal)


async def record_implicit_feedback(
    db: AsyncSession,
    is_positive: bool,
    trigger_phrase: str,
    strength: str,  # "strong", "moderate", "weak"
    message_id: Optional[str] = None,
    context: Optional[Dict] = None
) -> None:
    """
    Record implicit feedback detected from user message patterns.

    Args:
        db: Database session
        is_positive: True for positive signals, False for negative
        trigger_phrase: The phrase that triggered detection
        strength: Signal strength
        message_id: Associated message ID
        context: Additional context
    """
    collector = FeedbackCollector(db)

    # Scale value by strength
    strength_scale = {"strong": 1.0, "moderate": 0.7, "weak": 0.4}
    value = strength_scale.get(strength, 0.5)

    signal = FeedbackSignal(
        feedback_type=FeedbackType.IMPLICIT_POSITIVE if is_positive else FeedbackType.IMPLICIT_NEGATIVE,
        agent_id="sara",
        value=value,
        context={
            "trigger_phrase": trigger_phrase,
            "strength": strength,
            **(context or {})
        },
        evidence_id=message_id,
        evidence_type="implicit_feedback"
    )

    await collector.collect(signal)


async def record_lesson_outcome(
    db: AsyncSession,
    lesson_id: str,
    was_successful: bool,
    feedback_signal: Optional[str] = None,
    context: Optional[Dict] = None
) -> None:
    """
    Record the outcome of applying a lesson.

    Args:
        db: Database session
        lesson_id: ID of the lesson that was applied
        was_successful: True if positive feedback after lesson, False otherwise
        feedback_signal: The feedback phrase that indicated success/failure
        context: Additional context
    """
    collector = FeedbackCollector(db)

    signal = FeedbackSignal(
        feedback_type=FeedbackType.LESSON_APPLIED_SUCCESS if was_successful else FeedbackType.LESSON_APPLIED_FAILURE,
        agent_id="sara",
        value=1.0,
        context={
            "lesson_id": lesson_id,
            "feedback_signal": feedback_signal,
            **(context or {})
        },
        evidence_id=lesson_id,
        evidence_type="lesson_application"
    )

    await collector.collect(signal)
