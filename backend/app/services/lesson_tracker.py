"""
Lesson Tracker for Sara Learning System.

Tracks lesson effectiveness and handles auto-deactivation of
ineffective lessons.
"""

import logging
from typing import List, Optional, Dict
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class LessonTracker:
    """
    Tracks lesson effectiveness using exponential moving average.

    Lessons are auto-deactivated when:
    - effectiveness_score < 0.3
    - times_applied >= 5

    This ensures we don't keep injecting lessons that don't help.
    """

    # EMA smoothing factor (higher = more weight to recent outcomes)
    EMA_ALPHA = 0.3

    # Thresholds for auto-deactivation
    MIN_APPLICATIONS_FOR_DEACTIVATION = 5
    DEACTIVATION_THRESHOLD = 0.3

    async def record_success(
        self,
        db: Session,
        lesson_id: str,
        conversation_id: str,
        feedback_signal: Optional[str] = None,
        context_snippet: Optional[str] = None
    ) -> None:
        """
        Record that a lesson application was successful.

        Args:
            db: Database session
            lesson_id: The lesson that was applied
            conversation_id: The conversation where it was applied
            feedback_signal: The trigger phrase indicating success
            context_snippet: Brief context of the successful interaction
        """
        await self._record_outcome(
            db=db,
            lesson_id=lesson_id,
            conversation_id=conversation_id,
            outcome="success",
            feedback_signal=feedback_signal,
            context_snippet=context_snippet
        )

    async def record_failure(
        self,
        db: Session,
        lesson_id: str,
        conversation_id: str,
        feedback_signal: Optional[str] = None,
        context_snippet: Optional[str] = None
    ) -> None:
        """
        Record that a lesson application failed.

        Args:
            db: Database session
            lesson_id: The lesson that was applied
            conversation_id: The conversation where it was applied
            feedback_signal: The trigger phrase indicating failure
            context_snippet: Brief context of the failed interaction
        """
        await self._record_outcome(
            db=db,
            lesson_id=lesson_id,
            conversation_id=conversation_id,
            outcome="failure",
            feedback_signal=feedback_signal,
            context_snippet=context_snippet
        )

    async def _record_outcome(
        self,
        db: Session,
        lesson_id: str,
        conversation_id: str,
        outcome: str,
        feedback_signal: Optional[str] = None,
        context_snippet: Optional[str] = None
    ) -> None:
        """Internal method to record an outcome and update effectiveness."""
        try:
            # Update the most recent application record for this lesson/conversation
            db.execute(
                text("""
                    UPDATE lesson_applications
                    SET outcome = :outcome,
                        feedback_signal = :feedback_signal,
                        context_snippet = :context_snippet
                    WHERE lesson_id = :lesson_id
                      AND conversation_id = :conversation_id
                      AND outcome = 'unknown'
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {
                    "lesson_id": lesson_id,
                    "conversation_id": conversation_id,
                    "outcome": outcome,
                    "feedback_signal": feedback_signal,
                    "context_snippet": context_snippet[:500] if context_snippet else None
                }
            )

            # Update effectiveness score using EMA
            await self._update_effectiveness(db, lesson_id, outcome == "success")

            db.commit()

            logger.info(
                f"Recorded lesson outcome: {lesson_id} -> {outcome} "
                f"(signal: {feedback_signal})"
            )

        except Exception as e:
            logger.error(f"Failed to record lesson outcome: {e}")
            db.rollback()

    async def _update_effectiveness(
        self,
        db: Session,
        lesson_id: str,
        was_successful: bool
    ) -> None:
        """
        Update lesson effectiveness score using exponential moving average.

        EMA formula: new_score = alpha * new_value + (1 - alpha) * old_score
        """
        try:
            # Get current effectiveness score and times_applied
            result = db.execute(
                text("""
                    SELECT effectiveness_score, times_applied
                    FROM sara_reflection
                    WHERE id = :lesson_id
                """),
                {"lesson_id": lesson_id}
            ).fetchone()

            if not result:
                logger.warning(f"Lesson {lesson_id} not found for effectiveness update")
                return

            current_score = result.effectiveness_score if result.effectiveness_score is not None else 0.5
            times_applied = result.times_applied or 0

            # Calculate new score using EMA
            new_value = 1.0 if was_successful else 0.0
            new_score = self.EMA_ALPHA * new_value + (1 - self.EMA_ALPHA) * current_score

            # Update the score
            db.execute(
                text("""
                    UPDATE sara_reflection
                    SET effectiveness_score = :new_score,
                        updated_at = NOW()
                    WHERE id = :lesson_id
                """),
                {"lesson_id": lesson_id, "new_score": new_score}
            )

            # Check for auto-deactivation
            if (times_applied >= self.MIN_APPLICATIONS_FOR_DEACTIVATION and
                    new_score < self.DEACTIVATION_THRESHOLD):
                await self._deactivate_lesson(db, lesson_id, new_score, times_applied)

            logger.debug(
                f"Updated lesson {lesson_id} effectiveness: "
                f"{current_score:.3f} -> {new_score:.3f}"
            )

        except Exception as e:
            logger.error(f"Failed to update effectiveness: {e}")

    async def _deactivate_lesson(
        self,
        db: Session,
        lesson_id: str,
        score: float,
        times_applied: int
    ) -> None:
        """Deactivate an ineffective lesson."""
        try:
            db.execute(
                text("""
                    UPDATE sara_reflection
                    SET is_active = false,
                        updated_at = NOW()
                    WHERE id = :lesson_id
                """),
                {"lesson_id": lesson_id}
            )

            logger.info(
                f"Auto-deactivated lesson {lesson_id}: "
                f"score={score:.3f}, applications={times_applied}"
            )

        except Exception as e:
            logger.error(f"Failed to deactivate lesson: {e}")

    async def update_pending_applications(
        self,
        db: Session,
        conversation_id: str,
        was_successful: bool,
        feedback_signal: Optional[str] = None
    ) -> List[str]:
        """
        Update all pending (unknown outcome) applications for a conversation.

        Called when feedback is detected to update all lessons that were
        in context for that conversation.

        Returns:
            List of lesson IDs that were updated
        """
        try:
            # Find pending applications
            result = db.execute(
                text("""
                    SELECT DISTINCT lesson_id
                    FROM lesson_applications
                    WHERE conversation_id = :conversation_id
                      AND outcome = 'unknown'
                """),
                {"conversation_id": conversation_id}
            ).fetchall()

            if not result:
                return []

            lesson_ids = [row.lesson_id for row in result]

            # Update each
            for lesson_id in lesson_ids:
                if was_successful:
                    await self.record_success(
                        db=db,
                        lesson_id=lesson_id,
                        conversation_id=conversation_id,
                        feedback_signal=feedback_signal
                    )
                else:
                    await self.record_failure(
                        db=db,
                        lesson_id=lesson_id,
                        conversation_id=conversation_id,
                        feedback_signal=feedback_signal
                    )

            return lesson_ids

        except Exception as e:
            logger.error(f"Failed to update pending applications: {e}")
            return []

    async def get_lesson_stats(
        self,
        db: Session,
        lesson_id: str
    ) -> Optional[Dict]:
        """Get statistics for a specific lesson."""
        try:
            # Get lesson info
            lesson = db.execute(
                text("""
                    SELECT id, content, domain, confidence, times_applied,
                           effectiveness_score, is_active, created_at
                    FROM sara_reflection
                    WHERE id = :lesson_id
                """),
                {"lesson_id": lesson_id}
            ).fetchone()

            if not lesson:
                return None

            # Get application breakdown
            apps = db.execute(
                text("""
                    SELECT outcome, COUNT(*) as count
                    FROM lesson_applications
                    WHERE lesson_id = :lesson_id
                    GROUP BY outcome
                """),
                {"lesson_id": lesson_id}
            ).fetchall()

            outcomes = {row.outcome: row.count for row in apps}

            return {
                "id": lesson.id,
                "content": lesson.content,
                "domain": lesson.domain,
                "confidence": lesson.confidence,
                "times_applied": lesson.times_applied,
                "effectiveness_score": lesson.effectiveness_score,
                "is_active": lesson.is_active,
                "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
                "outcomes": {
                    "success": outcomes.get("success", 0),
                    "failure": outcomes.get("failure", 0),
                    "unknown": outcomes.get("unknown", 0)
                }
            }

        except Exception as e:
            logger.error(f"Failed to get lesson stats: {e}")
            return None


# Singleton instance
lesson_tracker = LessonTracker()


async def record_lesson_success(
    db: Session,
    lesson_id: str,
    conversation_id: str,
    feedback_signal: Optional[str] = None
) -> None:
    """Convenience function to record successful lesson application."""
    await lesson_tracker.record_success(
        db=db,
        lesson_id=lesson_id,
        conversation_id=conversation_id,
        feedback_signal=feedback_signal
    )


async def record_lesson_failure(
    db: Session,
    lesson_id: str,
    conversation_id: str,
    feedback_signal: Optional[str] = None
) -> None:
    """Convenience function to record failed lesson application."""
    await lesson_tracker.record_failure(
        db=db,
        lesson_id=lesson_id,
        conversation_id=conversation_id,
        feedback_signal=feedback_signal
    )


async def update_lessons_for_conversation(
    db: Session,
    conversation_id: str,
    was_successful: bool,
    feedback_signal: Optional[str] = None
) -> List[str]:
    """
    Update all pending lesson applications for a conversation.

    Returns list of lesson IDs that were updated.
    """
    return await lesson_tracker.update_pending_applications(
        db=db,
        conversation_id=conversation_id,
        was_successful=was_successful,
        feedback_signal=feedback_signal
    )
