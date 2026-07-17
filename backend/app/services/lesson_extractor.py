"""
Lesson Extractor for Sara Learning System.

Analyzes mistakes when negative feedback is detected and generates
concise, actionable lessons for future behavior modification.
"""

import logging
import json
import uuid
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx

from app.services.implicit_feedback_detector import ImplicitFeedback, SignalType
from app.services.embedding_service import embedding_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class MistakeType(str, Enum):
    """Categories of mistakes Sara can make."""
    MISUNDERSTANDING = "misunderstanding"  # Misunderstood user's intent
    WRONG_INFO = "wrong_info"  # Provided incorrect information
    WRONG_TONE = "wrong_tone"  # Tone was inappropriate
    TOO_VERBOSE = "too_verbose"  # Response was too long/detailed
    TOO_BRIEF = "too_brief"  # Response was too short/incomplete
    MISSED_CONTEXT = "missed_context"  # Ignored important context
    WRONG_ASSUMPTION = "wrong_assumption"  # Made incorrect assumption
    REPETITION = "repetition"  # Repeated information unnecessarily
    OFF_TOPIC = "off_topic"  # Response went off topic


class LessonDomain(str, Enum):
    """Domains for lesson categorization."""
    GENERAL = "general"
    FITNESS = "fitness"
    WORK = "work"
    PERSONAL = "personal"
    TECHNICAL = "technical"
    COMMUNICATION = "communication"
    SCHEDULING = "scheduling"
    HEALTH = "health"


@dataclass
class ExtractedLesson:
    """A lesson extracted from a mistake."""
    id: str
    mistake_type: MistakeType
    domain: LessonDomain
    lesson: str  # The concise lesson text (< 100 chars)
    when_to_apply: str  # Context for when this lesson applies
    confidence: float  # 0-1 confidence in the lesson
    source_context: str  # Conversation context that triggered this
    trigger_feedback: str  # The feedback phrase that triggered extraction


# Prompt for LLM to extract lessons
LESSON_EXTRACTION_PROMPT = """You are analyzing a conversation where the user indicated Sara made a mistake.

<previous_response>
{previous_response}
</previous_response>

<user_feedback>
{user_feedback}
</user_feedback>

<feedback_signal>
Signal type: {signal_type}
Trigger phrase: "{trigger_phrase}"
</feedback_signal>

Analyze what Sara did wrong and generate a concise lesson to prevent this mistake in the future.

Respond with ONLY a JSON object (no markdown):
{{
    "mistake_type": "one of: misunderstanding, wrong_info, wrong_tone, too_verbose, too_brief, missed_context, wrong_assumption, repetition, off_topic",
    "domain": "one of: general, fitness, work, personal, technical, communication, scheduling, health",
    "lesson": "A concise lesson under 100 characters. Format: 'When [context], [do/don't action]'",
    "when_to_apply": "Brief description of when this lesson should be applied",
    "confidence": 0.0-1.0
}}

Guidelines:
- The lesson must be actionable and specific
- Keep the lesson under 100 characters
- Focus on the "when" and "what" of the behavior change
- Confidence should be higher if the mistake and correction are clear"""


class LessonExtractor:
    """
    Extracts lessons from conversations where Sara made mistakes.

    When negative implicit feedback is detected, this service:
    1. Analyzes Sara's previous response and the user's correction
    2. Uses LLM to identify what went wrong
    3. Generates a concise, actionable lesson
    4. Stores it in sara_reflection for future prompt injection
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def create_lesson(
        self,
        db: Session,
        feedback: ImplicitFeedback,
        messages: List[dict],
        previous_response: Optional[str] = None
    ) -> Optional[ExtractedLesson]:
        """
        Create a lesson from negative feedback.

        Args:
            db: Database session
            feedback: The implicit feedback that triggered this
            messages: Recent conversation messages
            previous_response: Sara's previous response that received feedback

        Returns:
            ExtractedLesson if successfully created, None otherwise
        """
        if feedback.signal_type != SignalType.NEGATIVE:
            logger.debug("Skipping lesson extraction - not negative feedback")
            return None

        try:
            # Get Sara's previous response if not provided
            if not previous_response:
                previous_response = self._get_previous_assistant_response(messages)

            if not previous_response:
                logger.warning("No previous assistant response found for lesson extraction")
                return None

            # Get the user message that contained the feedback
            user_feedback = self._get_last_user_message(messages)
            if not user_feedback:
                logger.warning("No user message found for lesson extraction")
                return None

            # Extract lesson using LLM
            lesson_data = await self._extract_lesson_via_llm(
                previous_response=previous_response,
                user_feedback=user_feedback,
                feedback=feedback
            )

            if not lesson_data:
                logger.warning("LLM failed to extract lesson")
                return None

            # Create the lesson object
            lesson = ExtractedLesson(
                id=str(uuid.uuid4()),
                mistake_type=MistakeType(lesson_data.get("mistake_type", "misunderstanding")),
                domain=LessonDomain(lesson_data.get("domain", "general")),
                lesson=lesson_data.get("lesson", "")[:100],  # Enforce limit
                when_to_apply=lesson_data.get("when_to_apply", ""),
                confidence=min(1.0, max(0.0, lesson_data.get("confidence", 0.5))),
                source_context=f"{previous_response[:200]}... -> {user_feedback[:200]}",
                trigger_feedback=feedback.trigger_phrase
            )

            # Store in database
            await self._store_lesson(db, lesson)

            logger.info(
                f"Created lesson [{lesson.domain.value}]: {lesson.lesson} "
                f"(confidence: {lesson.confidence:.2f})"
            )

            return lesson

        except Exception as e:
            logger.error(f"Error creating lesson: {e}")
            return None

    async def _extract_lesson_via_llm(
        self,
        previous_response: str,
        user_feedback: str,
        feedback: ImplicitFeedback
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to analyze mistake and extract lesson."""
        try:
            prompt = LESSON_EXTRACTION_PROMPT.format(
                previous_response=previous_response[:1000],  # Limit context
                user_feedback=user_feedback[:500],
                signal_type=feedback.strength.value,
                trigger_phrase=feedback.trigger_phrase
            )

            # Use local LLM for lesson extraction (cheaper, faster)
            response = await self.client.post(
                f"{settings.bg_llm_primary_url}/chat/completions",
                json={
                    "model": settings.bg_llm_primary_model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,  # Low temperature for consistent extraction
                    "max_tokens": 300
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()

            # Parse JSON response
            # Handle potential markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            lesson_data = json.loads(content)
            return lesson_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM lesson response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM lesson extraction failed: {e}")
            return None

    async def _store_lesson(self, db: Session, lesson: ExtractedLesson) -> None:
        """Store the lesson in sara_reflection table."""
        try:
            # Generate embedding for the lesson
            embedding = await embedding_service.generate_embedding(
                f"{lesson.lesson} {lesson.when_to_apply}"
            )

            # Insert into sara_reflection as a "mistake" type reflection
            db.execute(
                text("""
                    INSERT INTO sara_reflection (
                        id, reflection_type, domain, content,
                        source_episodes, confidence, times_applied,
                        effectiveness_score, is_active, embedding,
                        trigger_context, created_at, updated_at
                    ) VALUES (
                        :id, :reflection_type, :domain, :content,
                        :source_episodes, :confidence, 0,
                        0.5, true, :embedding,
                        :trigger_context, NOW(), NOW()
                    )
                """),
                {
                    "id": lesson.id,
                    "reflection_type": "mistake",
                    "domain": lesson.domain.value,
                    "content": lesson.lesson,
                    "source_episodes": json.dumps([]),
                    "confidence": lesson.confidence,
                    "embedding": embedding,
                    "trigger_context": json.dumps({
                        "mistake_type": lesson.mistake_type.value,
                        "when_to_apply": lesson.when_to_apply,
                        "source_context": lesson.source_context[:500],
                        "trigger_feedback": lesson.trigger_feedback
                    })
                }
            )
            db.commit()
            logger.info(f"Stored lesson {lesson.id} in sara_reflection")

        except Exception as e:
            logger.error(f"Failed to store lesson: {e}")
            db.rollback()
            raise

    def _get_previous_assistant_response(self, messages: List[dict]) -> Optional[str]:
        """Get the most recent assistant message."""
        for msg in reversed(messages):
            if isinstance(msg, dict):
                if msg.get("role") == "assistant":
                    return msg.get("content")
            elif hasattr(msg, "role") and msg.role == "assistant":
                return msg.content
        return None

    def _get_last_user_message(self, messages: List[dict]) -> Optional[str]:
        """Get the most recent user message."""
        for msg in reversed(messages):
            if isinstance(msg, dict):
                if msg.get("role") == "user":
                    return msg.get("content")
            elif hasattr(msg, "role") and msg.role == "user":
                return msg.content
        return None


# Singleton instance
lesson_extractor = LessonExtractor()


async def create_lesson_from_feedback(
    db: Session,
    feedback: ImplicitFeedback,
    messages: List[dict],
    previous_response: Optional[str] = None
) -> Optional[ExtractedLesson]:
    """
    Convenience function to create a lesson from negative feedback.

    Args:
        db: Database session
        feedback: The implicit feedback
        messages: Conversation messages
        previous_response: Sara's previous response

    Returns:
        ExtractedLesson if created, None otherwise
    """
    return await lesson_extractor.create_lesson(
        db=db,
        feedback=feedback,
        messages=messages,
        previous_response=previous_response
    )
