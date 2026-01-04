"""
Sara Identity Service

This service manages Sara's self-knowledge, reflections, and relationship state.
It enables Sara to:
1. Learn from her mistakes and patterns
2. Understand what works well with David
3. Track the evolution of their relationship
4. Apply learned behaviors to future interactions
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc
import logging
import json

from app.models.cognitive import SaraReflection, RelationshipState

logger = logging.getLogger(__name__)


class SaraIdentityService:
    """
    Service for managing Sara's self-reflections and relationship awareness.
    """

    def __init__(self):
        self._llm_client = None
        self._embedding_service = None

    def _get_llm_client(self):
        """Lazy-load LLM client"""
        if self._llm_client:
            return self._llm_client
        try:
            from app.core.llm import llm_client
            self._llm_client = llm_client
            return self._llm_client
        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
            return None

    def _get_embedding_service(self):
        """Lazy-load embedding service"""
        if self._embedding_service:
            return self._embedding_service
        try:
            from app.services.embeddings import get_embedding
            self._embedding_service = get_embedding
            return self._embedding_service
        except Exception as e:
            logger.error(f"Failed to initialize embedding service: {e}")
            return None

    async def analyze_conversation_for_reflections(
        self,
        db: Session,
        conversation_episodes: List[Dict],
        user_feedback: Optional[Dict] = None
    ) -> List[SaraReflection]:
        """
        Analyze a completed conversation for self-improvement opportunities.
        Run after each conversation or during dream processing.
        """
        reflections = []

        # Extract Sara's responses from conversation
        sara_responses = [ep for ep in conversation_episodes if ep.get('role') == 'assistant']
        user_messages = [ep for ep in conversation_episodes if ep.get('role') == 'user']

        if not sara_responses or not user_messages:
            return reflections

        # Check for potential mistakes
        mistake_reflection = await self._detect_mistakes(
            sara_responses, user_messages, user_feedback
        )
        if mistake_reflection:
            reflections.append(mistake_reflection)

        # Check for patterns in Sara's behavior
        pattern_reflection = await self._detect_self_patterns(sara_responses)
        if pattern_reflection:
            reflections.append(pattern_reflection)

        # Check for preference signals from user
        preference_reflection = await self._detect_user_preferences(
            user_messages, sara_responses, user_feedback
        )
        if preference_reflection:
            reflections.append(preference_reflection)

        # Save reflections with embeddings
        embedding_fn = self._get_embedding_service()
        for reflection in reflections:
            if embedding_fn:
                try:
                    reflection.embedding = await embedding_fn(reflection.content)
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for reflection: {e}")
            db.add(reflection)

        db.commit()
        logger.info(f"Created {len(reflections)} new reflections from conversation")
        return reflections

    async def _detect_mistakes(
        self,
        sara_responses: List[Dict],
        user_messages: List[Dict],
        user_feedback: Optional[Dict]
    ) -> Optional[SaraReflection]:
        """Detect if Sara made mistakes in this conversation."""

        llm = self._get_llm_client()
        if not llm:
            return None

        analysis_prompt = f"""Analyze this conversation between Sara (assistant) and David (user).

Identify if Sara made any mistakes, misunderstandings, or suboptimal responses.

Conversation:
{self._format_conversation(sara_responses, user_messages)}

User feedback/ratings (if any): {json.dumps(user_feedback) if user_feedback else "None"}

If Sara made a mistake, respond with ONLY valid JSON:
{{
    "made_mistake": true,
    "mistake_description": "Brief description of what went wrong",
    "what_sara_should_learn": "What Sara should remember for next time",
    "domain": "The domain this applies to (fitness, work, personal, technical, etc.)",
    "confidence": 0.0-1.0 how confident you are this was a real mistake
}}

If no clear mistakes, respond with ONLY valid JSON:
{{"made_mistake": false}}"""

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are analyzing Sara's conversation for mistakes. Respond with ONLY valid JSON."},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            response_text = result["choices"][0]["message"]["content"].strip()
            # Try to extract JSON from response
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            parsed = json.loads(response_text)

            if parsed.get("made_mistake"):
                return SaraReflection(
                    reflection_type="mistake",
                    domain=parsed.get("domain", "general"),
                    content=parsed["what_sara_should_learn"],
                    source_episodes=[ep.get("id") for ep in sara_responses if ep.get("id")],
                    confidence=parsed.get("confidence", 0.5)
                )
        except Exception as e:
            logger.warning(f"Failed to detect mistakes: {e}")

        return None

    async def _detect_self_patterns(
        self,
        sara_responses: List[Dict]
    ) -> Optional[SaraReflection]:
        """Detect patterns in Sara's own behavior."""

        llm = self._get_llm_client()
        if not llm:
            return None

        responses_text = "\n".join([
            r.get('content', '')[:500] for r in sara_responses
        ])

        analysis_prompt = f"""Analyze Sara's responses in this conversation for behavioral patterns.

Sara's responses:
{responses_text}

Look for:
- Verbosity (too long when brevity would help)
- Repetition (saying the same thing multiple ways)
- Tone mismatches
- Over-explaining or under-explaining
- Tool usage patterns (too many searches, redundant calls)

If you find a notable pattern Sara should be aware of, respond with ONLY valid JSON:
{{
    "found_pattern": true,
    "pattern_description": "What pattern you noticed",
    "self_note": "What Sara should remember about her own tendencies",
    "domain": "general or specific domain",
    "confidence": 0.0-1.0
}}

If no notable patterns, respond with ONLY valid JSON:
{{"found_pattern": false}}"""

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are analyzing Sara's behavior patterns. Respond with ONLY valid JSON."},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            response_text = result["choices"][0]["message"]["content"].strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            parsed = json.loads(response_text)

            if parsed.get("found_pattern"):
                return SaraReflection(
                    reflection_type="pattern",
                    domain=parsed.get("domain", "general"),
                    content=parsed["self_note"],
                    source_episodes=[],
                    confidence=parsed.get("confidence", 0.5)
                )
        except Exception as e:
            logger.warning(f"Failed to detect patterns: {e}")

        return None

    async def _detect_user_preferences(
        self,
        user_messages: List[Dict],
        sara_responses: List[Dict],
        user_feedback: Optional[Dict]
    ) -> Optional[SaraReflection]:
        """Detect user preferences from interaction patterns."""

        llm = self._get_llm_client()
        if not llm:
            return None

        analysis_prompt = f"""Analyze this conversation for signals about David's preferences.

Conversation:
{self._format_conversation(sara_responses, user_messages)}

User feedback/ratings: {json.dumps(user_feedback) if user_feedback else "None"}

Look for signals about:
- Preferred response length
- Tone preferences
- Topics he engages with more/less
- What made him satisfied vs frustrated
- Communication style preferences

If you detect a preference Sara should remember, respond with ONLY valid JSON:
{{
    "found_preference": true,
    "preference_description": "What preference you detected",
    "how_sara_should_adapt": "How Sara should adjust her behavior",
    "domain": "The domain this applies to",
    "confidence": 0.0-1.0
}}

If no clear preferences detected, respond with ONLY valid JSON:
{{"found_preference": false}}"""

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are analyzing user preferences. Respond with ONLY valid JSON."},
                    {"role": "user", "content": analysis_prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            response_text = result["choices"][0]["message"]["content"].strip()
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            parsed = json.loads(response_text)

            if parsed.get("found_preference"):
                return SaraReflection(
                    reflection_type="preference",
                    domain=parsed.get("domain", "general"),
                    content=parsed["how_sara_should_adapt"],
                    source_episodes=[],
                    confidence=parsed.get("confidence", 0.5)
                )
        except Exception as e:
            logger.warning(f"Failed to detect preferences: {e}")

        return None

    async def get_relevant_reflections(
        self,
        db: Session,
        query: str,
        domain: Optional[str] = None,
        limit: int = 5
    ) -> List[SaraReflection]:
        """Retrieve reflections relevant to the current context."""

        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            logger.warning("Embedding service not available for reflection retrieval")
            return []

        try:
            query_embedding = await embedding_fn(query)

            # Build query for active reflections
            from sqlalchemy import text

            # Use L2 distance for similarity search
            sql = text("""
                SELECT id, reflection_type, domain, content, confidence, times_applied,
                       effectiveness_score, is_active, created_at,
                       embedding <-> :query_embedding AS distance
                FROM sara_reflection
                WHERE is_active = true
                AND embedding IS NOT NULL
                """ + (f"AND domain = :domain" if domain else "") + """
                ORDER BY distance ASC
                LIMIT :limit
            """)

            params = {"query_embedding": str(query_embedding), "limit": limit}
            if domain:
                params["domain"] = domain

            result = db.execute(sql, params)
            rows = result.fetchall()

            reflections = []
            for row in rows:
                reflection = db.query(SaraReflection).filter(SaraReflection.id == row[0]).first()
                if reflection:
                    reflections.append(reflection)

            return reflections

        except Exception as e:
            logger.error(f"Failed to retrieve relevant reflections: {e}")
            return []

    async def mark_reflection_applied(
        self,
        db: Session,
        reflection_id: str,
        was_effective: Optional[bool] = None
    ):
        """Track when a reflection influenced a response."""

        reflection = db.query(SaraReflection).filter(SaraReflection.id == reflection_id).first()

        if reflection:
            reflection.times_applied += 1
            if was_effective is not None:
                # Update effectiveness score (exponential moving average)
                if reflection.effectiveness_score is None:
                    reflection.effectiveness_score = 1.0 if was_effective else 0.0
                else:
                    alpha = 0.3
                    new_score = 1.0 if was_effective else 0.0
                    reflection.effectiveness_score = (
                        alpha * new_score + (1 - alpha) * reflection.effectiveness_score
                    )
            reflection.updated_at = datetime.now(timezone.utc)
            db.commit()

    async def update_relationship_state(
        self,
        db: Session,
        conversation_episodes: List[Dict]
    ):
        """Update the relationship state after a conversation."""

        # Get or create relationship state (single record)
        state = db.query(RelationshipState).first()

        if not state:
            state = RelationshipState(
                first_interaction=datetime.now(timezone.utc)
            )
            db.add(state)

        # Update counts
        state.total_conversations += 1
        state.total_episodes += len(conversation_episodes)

        # Extract topics from conversation
        topics = await self._extract_topics(conversation_episodes)
        topics_dict = state.topics_discussed or {}
        for topic in topics:
            topics_dict[topic] = topics_dict.get(topic, 0) + 1
        state.topics_discussed = topics_dict

        # Update phase based on depth of relationship
        state.phase = self._calculate_relationship_phase(state)
        state.last_updated = datetime.now(timezone.utc)

        db.commit()
        logger.info(f"Updated relationship state: phase={state.phase}, conversations={state.total_conversations}")

    def _calculate_relationship_phase(self, state: RelationshipState) -> str:
        """Determine relationship phase based on interaction history."""

        if state.total_conversations < 10:
            return "early"
        elif state.total_conversations < 50:
            return "developing"
        elif state.total_conversations < 200:
            return "established"
        else:
            return "deep"

    async def get_relationship_context(self, db: Session) -> Dict[str, Any]:
        """Get relationship context for inclusion in prompts."""

        state = db.query(RelationshipState).first()

        if not state:
            return {"phase": "new", "context": "This is a new relationship."}

        # Calculate relationship duration
        if state.first_interaction:
            duration = datetime.now(timezone.utc) - state.first_interaction.replace(tzinfo=timezone.utc)
            duration_str = f"{duration.days} days"
        else:
            duration_str = "unknown"

        # Get top topics
        topics_dict = state.topics_discussed or {}
        top_topics = sorted(
            topics_dict.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        return {
            "phase": state.phase,
            "duration": duration_str,
            "total_conversations": state.total_conversations,
            "top_topics": top_topics,
            "shared_references": state.shared_references or [],
            "communication_preferences": state.communication_preferences or {}
        }

    def _format_conversation(self, sara_responses: List, user_messages: List) -> str:
        """Format conversation for analysis."""
        all_messages = []
        for msg in user_messages:
            all_messages.append(("David", msg.get("content", "")[:1000], msg.get("created_at")))
        for msg in sara_responses:
            all_messages.append(("Sara", msg.get("content", "")[:1000], msg.get("created_at")))

        # Sort by timestamp if available
        all_messages.sort(key=lambda x: x[2] if x[2] else datetime.min)

        return "\n".join([f"{role}: {content}" for role, content, _ in all_messages])

    async def _extract_topics(self, episodes: List[Dict]) -> List[str]:
        """Extract main topics from conversation."""
        topics = []
        for ep in episodes:
            if ep.get("topics"):
                topics.extend(ep["topics"])
        return list(set(topics))

    async def get_recent_reflections(
        self,
        db: Session,
        reflection_type: Optional[str] = None,
        limit: int = 20
    ) -> List[SaraReflection]:
        """Get recent reflections, optionally filtered by type."""

        query = db.query(SaraReflection).filter(SaraReflection.is_active == True)

        if reflection_type:
            query = query.filter(SaraReflection.reflection_type == reflection_type)

        return query.order_by(desc(SaraReflection.created_at)).limit(limit).all()


# Global service instance
sara_identity_service = SaraIdentityService()
