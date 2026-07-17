"""
Lesson Injection Service for Sara Learning System.

Retrieves relevant lessons from sara_reflection and formats them
for injection into the system prompt.
"""

import logging
import json
import asyncio
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.embedding_service import embedding_service
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievedLesson:
    """A lesson retrieved for potential injection."""
    id: str
    domain: str
    content: str
    when_to_apply: str
    confidence: float
    effectiveness_score: float
    times_applied: int
    similarity_score: float
    recency_score: float
    composite_score: float


class LessonInjectionService:
    """
    Retrieves and formats lessons for prompt injection.

    Uses composite scoring to select the most relevant lessons:
    - Semantic similarity to current query
    - Domain matching
    - Effectiveness score (lessons that worked before)
    - Recency (recently created/applied lessons may be more relevant)
    """

    # Weights for composite scoring
    SIMILARITY_WEIGHT = 0.4
    EFFECTIVENESS_WEIGHT = 0.3
    RECENCY_WEIGHT = 0.15
    CONFIDENCE_WEIGHT = 0.15

    # Recency decay: lessons older than this get reduced scores
    RECENCY_DECAY_DAYS = 30

    async def get_relevant_lessons(
        self,
        db: Session,
        query: str,
        domain_hint: Optional[str] = None,
        limit: int = 5,
        min_effectiveness: float = 0.3
    ) -> List[RetrievedLesson]:
        """
        Retrieve lessons relevant to the current query.

        Args:
            db: Database session
            query: The user's current message/query
            domain_hint: Optional domain to prioritize
            limit: Maximum number of lessons to return
            min_effectiveness: Minimum effectiveness score threshold

        Returns:
            List of relevant lessons sorted by composite score
        """
        try:
            # Generate embedding for the query
            query_embedding = await asyncio.wait_for(
                embedding_service.generate_embedding(query),
                timeout=2.5
            )
            if not query_embedding:
                logger.warning("Failed to generate query embedding for lesson retrieval")
                return []

            # Query for active lessons (reflection_type = 'mistake')
            # with vector similarity search
            result = db.execute(
                text("""
                    SELECT
                        id,
                        domain,
                        content,
                        confidence,
                        times_applied,
                        effectiveness_score,
                        trigger_context,
                        created_at,
                        last_applied_at,
                        1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                    FROM sara_reflection
                    WHERE reflection_type = 'mistake'
                      AND is_active = true
                      AND (effectiveness_score IS NULL OR effectiveness_score >= :min_effectiveness)
                    ORDER BY embedding <=> CAST(:query_embedding AS vector)
                    LIMIT :limit_count
                """),
                {
                    "query_embedding": str(query_embedding),
                    "min_effectiveness": min_effectiveness,
                    "limit_count": limit * 2  # Fetch extra for filtering
                }
            ).fetchall()

            if not result:
                return []

            # Process and score results
            lessons = []
            now = datetime.now(timezone.utc)

            for row in result:
                # Parse trigger_context for when_to_apply
                trigger_context = row.trigger_context or {}
                if isinstance(trigger_context, str):
                    try:
                        trigger_context = json.loads(trigger_context)
                    except json.JSONDecodeError:
                        trigger_context = {}

                when_to_apply = trigger_context.get("when_to_apply", "")

                # Calculate recency score
                created_at = row.created_at
                if created_at:
                    days_old = (now - created_at).days if hasattr(created_at, 'days') else (now - created_at).days
                    recency_score = max(0, 1 - (days_old / self.RECENCY_DECAY_DAYS))
                else:
                    recency_score = 0.5

                # Get scores
                similarity = row.similarity or 0
                effectiveness = row.effectiveness_score if row.effectiveness_score is not None else 0.5
                confidence = row.confidence or 0.5

                # Calculate composite score
                composite = (
                    self.SIMILARITY_WEIGHT * similarity +
                    self.EFFECTIVENESS_WEIGHT * effectiveness +
                    self.RECENCY_WEIGHT * recency_score +
                    self.CONFIDENCE_WEIGHT * confidence
                )

                # Boost if domain matches hint
                if domain_hint and row.domain == domain_hint:
                    composite *= 1.2

                lessons.append(RetrievedLesson(
                    id=row.id,
                    domain=row.domain or "general",
                    content=row.content,
                    when_to_apply=when_to_apply,
                    confidence=confidence,
                    effectiveness_score=effectiveness,
                    times_applied=row.times_applied or 0,
                    similarity_score=similarity,
                    recency_score=recency_score,
                    composite_score=composite
                ))

            # Sort by composite score and limit
            lessons.sort(key=lambda x: x.composite_score, reverse=True)
            return lessons[:limit]

        except asyncio.TimeoutError:
            logger.warning("Lesson retrieval embedding timed out (skipping)")
            return []
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"Error retrieving lessons: {e}")
            return []

    def format_lessons_for_prompt(
        self,
        lessons: List[RetrievedLesson],
        max_chars: int = 800
    ) -> str:
        """
        Format lessons as XML for system prompt injection.

        Args:
            lessons: List of lessons to format
            max_chars: Maximum characters for the formatted output

        Returns:
            XML-formatted string for prompt injection
        """
        if not lessons:
            return ""

        lines = [
            "<sara_lessons>",
            "  <note>Apply these lessons when relevant. These are learnings from past interactions.</note>"
        ]

        char_count = sum(len(line) for line in lines)

        for lesson in lessons:
            # Format each lesson
            confidence_label = "high" if lesson.confidence >= 0.7 else "medium"
            lesson_line = f'  <lesson domain="{lesson.domain}" confidence="{confidence_label}">'
            content_line = f"    {lesson.content}"
            close_line = "  </lesson>"

            # Check if adding this lesson would exceed limit
            new_chars = len(lesson_line) + len(content_line) + len(close_line) + 6  # newlines
            if char_count + new_chars > max_chars:
                break

            lines.append(lesson_line)
            lines.append(content_line)
            lines.append(close_line)
            char_count += new_chars

        lines.append("</sara_lessons>")

        return "\n".join(lines)

    async def get_lessons_for_injection(
        self,
        db: Session,
        query: str,
        domain_hint: Optional[str] = None,
        limit: int = 5
    ) -> tuple[str, List[str]]:
        """
        Get formatted lessons ready for prompt injection.

        Returns:
            Tuple of (formatted_string, list_of_lesson_ids)
        """
        lessons = await self.get_relevant_lessons(
            db=db,
            query=query,
            domain_hint=domain_hint,
            limit=limit
        )

        if not lessons:
            return "", []

        formatted = self.format_lessons_for_prompt(lessons)
        lesson_ids = [lesson.id for lesson in lessons]

        logger.info(
            f"Prepared {len(lessons)} lessons for injection "
            f"(top score: {lessons[0].composite_score:.3f})"
        )

        return formatted, lesson_ids

    async def record_lesson_application(
        self,
        db: Session,
        lesson_ids: List[str],
        conversation_id: str,
        message_id: Optional[str] = None
    ) -> None:
        """
        Record that lessons were injected into a conversation.

        This creates pending application records that will be updated
        when feedback is received.
        """
        if not lesson_ids:
            return

        try:
            for lesson_id in lesson_ids:
                # Insert application record
                db.execute(
                    text("""
                        INSERT INTO lesson_applications (
                            lesson_id, conversation_id, message_id, outcome, created_at
                        ) VALUES (
                            :lesson_id, :conversation_id, :message_id, 'unknown', NOW()
                        )
                    """),
                    {
                        "lesson_id": lesson_id,
                        "conversation_id": conversation_id,
                        "message_id": message_id
                    }
                )

                # Update times_applied and last_applied_at
                db.execute(
                    text("""
                        UPDATE sara_reflection
                        SET times_applied = COALESCE(times_applied, 0) + 1,
                            last_applied_at = NOW()
                        WHERE id = :lesson_id
                    """),
                    {"lesson_id": lesson_id}
                )

            db.commit()
            logger.debug(f"Recorded {len(lesson_ids)} lesson applications")

        except Exception as e:
            logger.error(f"Failed to record lesson applications: {e}")
            db.rollback()


# Singleton instance
lesson_injection_service = LessonInjectionService()


async def inject_lessons(
    db: Session,
    query: str,
    domain_hint: Optional[str] = None,
    limit: int = 5
) -> tuple[str, List[str]]:
    """
    Convenience function to get lessons for prompt injection.

    Args:
        db: Database session
        query: Current user query
        domain_hint: Optional domain to prioritize
        limit: Maximum lessons to inject

    Returns:
        Tuple of (formatted_lesson_string, list_of_lesson_ids)
    """
    return await lesson_injection_service.get_lessons_for_injection(
        db=db,
        query=query,
        domain_hint=domain_hint,
        limit=limit
    )
