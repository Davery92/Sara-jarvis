"""
Insight Injection Service
Proactively surfaces dream insights and cross-domain patterns during conversations.

Updated to support:
- Proactive vs contextual vs passive surfacing strategies
- Lower thresholds for initial rollout
- Recency and feedback-based scoring adjustments
- Expiry checking
- Cross-domain pattern correlations (git, health, food, home, mood)
"""
import logging
from datetime import datetime, timedelta
from app.core.timezone import naive_local_now
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Pattern context keywords for relevance matching
PATTERN_CONTEXT_KEYWORDS = {
    "productivity": ["git", "commit", "code", "work", "productive", "focus"],
    "sleep": ["sleep", "rest", "tired", "energy", "awake", "morning"],
    "health": ["health", "hrv", "heart", "exercise", "workout", "recovery"],
    "food": ["food", "eat", "meal", "protein", "calories", "nutrition", "diet"],
    "mood": ["mood", "feeling", "happy", "stress", "anxious", "motivated"],
    "home": ["home", "temperature", "lights", "morning", "routine"],
}


class InsightInjectionService:
    """
    Surfaces dream insights proactively during conversations.
    Implements intelligent decision logic for when/how to mention insights.
    """

    def __init__(self, db_session: AsyncSession, redis_client=None):
        self.db = db_session
        self.redis = redis_client

        # Thresholds - lowered for initial rollout (tune based on feedback)
        self.SEMANTIC_THRESHOLD = 0.55  # Lowered from 0.70
        self.MIN_CONFIDENCE = 0.4  # Lowered from 0.5
        self.MENTION_COOLDOWN_HOURS = 12  # Reduced from 24
        self.MAX_CONTEXTUAL_PER_CONVERSATION = 2
        self.MAX_PROACTIVE_PER_CONVERSATION = 1
        self.MIN_TURNS_BETWEEN_INSIGHTS = 5

    async def get_relevant_insights(
        self,
        user_id: str,
        conversation_text: str,
        conversation_embedding: List[float],
        conversation_id: Optional[str] = None,
        surface_strategy: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get insights relevant to current conversation context.

        Args:
            user_id: User identifier
            conversation_text: Recent conversation text for semantic matching
            conversation_embedding: Vector embedding of conversation context
            conversation_id: Current conversation ID for tracking mentions
            surface_strategy: Filter by strategy ('proactive', 'contextual', or None for both)
            limit: Maximum number of insights to return

        Returns:
            List of insight dictionaries with relevance scores
        """
        try:
            # Build strategy filter
            strategy_filter = ""
            if surface_strategy:
                strategy_filter = f"AND di.surface_strategy = '{surface_strategy}'"

            # Query insights with semantic similarity and new fields
            query = text(f"""
                WITH recent_mentions AS (
                    SELECT insight_id, MAX(mentioned_at) as last_mentioned
                    FROM insight_mention_log
                    WHERE user_id = :user_id
                        AND mentioned_at > NOW() - INTERVAL '12 hours'
                    GROUP BY insight_id
                ),
                insight_feedback AS (
                    SELECT insight_id,
                           COUNT(*) FILTER (WHERE engagement_type = 'positive') as positive_count,
                           COUNT(*) FILTER (WHERE engagement_type = 'negative') as negative_count
                    FROM insight_mention_log
                    WHERE user_id = :user_id
                    GROUP BY insight_id
                )
                SELECT
                    di.id,
                    di.user_id,
                    di.dream_date,
                    di.insight_type,
                    di.confidence,
                    di.title,
                    di.content,
                    di.related_episodes,
                    di.surfaced_at,
                    di.user_feedback,
                    di.surface_strategy,
                    di.evidence,
                    di.expiry_at,
                    di.surfaced_count,
                    di.last_surfaced_at,
                    CASE
                        WHEN di.embedding IS NULL THEN 0.5
                        ELSE 1 - (di.embedding <=> CAST(:embedding AS vector))
                    END as similarity,
                    rm.last_mentioned,
                    COALESCE(if_fb.positive_count, 0) as positive_feedback,
                    COALESCE(if_fb.negative_count, 0) as negative_feedback
                FROM dream_insight di
                LEFT JOIN recent_mentions rm ON di.id = rm.insight_id
                LEFT JOIN insight_feedback if_fb ON di.id = if_fb.insight_id
                WHERE di.user_id = :user_id
                    AND di.confidence >= :min_confidence
                    AND rm.last_mentioned IS NULL  -- Not mentioned recently
                    AND (di.expiry_at IS NULL OR di.expiry_at > NOW())  -- Not expired
                    AND di.surface_strategy != 'passive'  -- Passive insights never auto-surface
                    {strategy_filter}
                ORDER BY
                    -- Proactive insights get priority boost
                    CASE WHEN di.surface_strategy = 'proactive' THEN 0.1 ELSE 0 END DESC,
                    -- Then by similarity (if embedding exists)
                    CASE WHEN di.embedding IS NOT NULL THEN 1 - (di.embedding <=> CAST(:embedding AS vector)) ELSE 0.5 END DESC,
                    -- Then by confidence
                    di.confidence DESC,
                    -- Prefer insights not yet surfaced
                    di.surfaced_count ASC,
                    -- Then by recency
                    di.dream_date DESC
                LIMIT :limit
            """)

            result = await self.db.execute(
                query,
                {
                    "user_id": user_id,
                    "embedding": str(conversation_embedding),
                    "min_confidence": self.MIN_CONFIDENCE,
                    "limit": limit
                }
            )

            rows = result.fetchall()

            insights = []
            for row in rows:
                insights.append({
                    "id": row[0],
                    "user_id": row[1],
                    "dream_date": row[2],
                    "insight_type": row[3],
                    "confidence": row[4],
                    "title": row[5],
                    "content": row[6],
                    "related_episodes": row[7],
                    "surfaced_at": row[8],
                    "user_feedback": row[9],
                    "surface_strategy": row[10] or "contextual",
                    "evidence": row[11],
                    "expiry_at": row[12],
                    "surfaced_count": row[13] or 0,
                    "last_surfaced_at": row[14],
                    "similarity": float(row[15]) if row[15] else 0.5,
                    "last_mentioned": row[16],
                    "positive_feedback": row[17] or 0,
                    "negative_feedback": row[18] or 0
                })

            logger.info(f"📊 Found {len(insights)} candidate insights for user {user_id[:8]}")
            return insights

        except Exception as e:
            logger.error(f"Error getting relevant insights: {e}", exc_info=True)
            return []

    def calculate_surface_score(
        self,
        insight: Dict[str, Any],
        conversation_context: Dict[str, Any]
    ) -> float:
        """
        Calculate a composite score for whether to surface this insight.

        Scoring factors:
        - Base: semantic similarity
        - Boost: high confidence, proactive strategy, never surfaced
        - Penalty: recently surfaced, negative feedback history
        """
        score = 0.0

        # Base: semantic similarity (0-1)
        similarity = insight.get("similarity", 0.5)
        score += similarity * 0.4  # 40% weight

        # Confidence factor (0-1)
        confidence = insight.get("confidence", 0.5)
        score += confidence * 0.25  # 25% weight

        # Proactive boost
        if insight.get("surface_strategy") == "proactive":
            score += 0.15

        # Never-surfaced boost
        if insight.get("surfaced_count", 0) == 0:
            score += 0.1

        # Recency boost (insights from today/yesterday)
        dream_date = insight.get("dream_date")
        if dream_date:
            days_old = (naive_local_now() - dream_date).days if isinstance(dream_date, datetime) else 7
            if days_old <= 1:
                score += 0.1
            elif days_old <= 3:
                score += 0.05

        # Feedback adjustments
        positive = insight.get("positive_feedback", 0)
        negative = insight.get("negative_feedback", 0)
        if positive > negative:
            score += 0.05 * min(positive - negative, 3)  # Max +0.15
        elif negative > positive:
            score -= 0.1 * min(negative - positive, 2)  # Max -0.2

        # User engagement boost (if asking questions, they're engaged)
        if conversation_context.get("user_asking_question"):
            score += 0.05

        return min(1.0, max(0.0, score))

    async def should_surface_now(
        self,
        insight: Dict[str, Any],
        conversation_context: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], float]:
        """
        Decide if this insight should be surfaced in current turn.

        Returns:
            (should_surface, reason, score) tuple
        """
        # Don't surface if already mentioned recently
        if insight.get("last_mentioned"):
            time_since_mention = naive_local_now() - insight["last_mentioned"]
            if time_since_mention < timedelta(hours=self.MENTION_COOLDOWN_HOURS):
                return False, "mentioned_recently", 0.0

        # Check if we've hit limits for this conversation
        insights_surfaced = conversation_context.get("insights_surfaced_count", 0)
        strategy = insight.get("surface_strategy", "contextual")

        if strategy == "proactive" and insights_surfaced >= self.MAX_PROACTIVE_PER_CONVERSATION:
            return False, "proactive_limit_reached", 0.0
        elif insights_surfaced >= self.MAX_CONTEXTUAL_PER_CONVERSATION:
            return False, "contextual_limit_reached", 0.0

        # Check turn spacing
        turn_count = conversation_context.get("turn_count", 0)
        last_insight_turn = conversation_context.get("last_insight_turn", -100)

        if turn_count - last_insight_turn < self.MIN_TURNS_BETWEEN_INSIGHTS:
            return False, "too_soon_after_last_insight", 0.0

        # Don't surface in first turn (let conversation develop)
        if turn_count < 2:
            return False, "too_early", 0.0

        # Calculate composite score
        score = self.calculate_surface_score(insight, conversation_context)

        # Threshold depends on strategy
        if strategy == "proactive":
            # Proactive insights have lower threshold - they're meant to be surfaced
            threshold = 0.35
        else:
            # Contextual insights need stronger relevance
            threshold = 0.45

        if score >= threshold:
            return True, f"score_{score:.2f}", score
        else:
            return False, f"below_threshold_{score:.2f}", score

    def format_insight_injection(
        self,
        insight: Dict[str, Any],
        injection_style: str = "gentle"
    ) -> str:
        """
        Format insight for injection into conversation.

        Args:
            insight: Insight dictionary
            injection_style: How to frame the insight
                - "gentle": Soft suggestion
                - "direct": Direct statement
                - "question": Posed as a question

        Returns:
            Formatted text for injection
        """
        content = insight.get("content", "")
        insight_type = insight.get("insight_type", "pattern")

        # Map insight types to natural language prefixes
        type_prefixes = {
            "behavioral_pattern": "I've noticed a pattern:",
            "connection": "This reminds me of something related:",
            "unresolved_thread": "By the way,",
            "emerging_pattern": "I've been noticing:",
            "contradiction": "Interestingly,",
            "wellbeing_signal": "I wanted to mention:",
            # Legacy types
            "pattern": "I've noticed:",
            "trend": "I've observed over time:",
            "forgotten_gem": "This reminds me of something from earlier:",
            "fitness_trend": "Regarding your training:",
        }

        if injection_style == "gentle":
            prefix = type_prefixes.get(insight_type, "Something that might be relevant:")
            formatted = f"{prefix} {content}"

        elif injection_style == "direct":
            title = insight.get("title", "Insight")
            formatted = f"**{title}**: {content}"

        elif injection_style == "question":
            # Frame as a question to invite engagement
            if insight_type == "unresolved_thread":
                formatted = f"{content}"  # These are already phrased as questions
            else:
                formatted = f"I was thinking about this: {content} - does that resonate?"

        else:
            formatted = content

        return formatted

    async def log_mention(
        self,
        user_id: str,
        insight_id: str,
        conversation_id: str
    ):
        """Log that an insight was mentioned and update surfaced_count."""
        try:
            # Insert mention log
            insert_query = text("""
                INSERT INTO insight_mention_log (
                    user_id, insight_id, conversation_id,
                    mentioned_at, user_engaged, engagement_type, engaged_at
                ) VALUES (
                    :user_id, :insight_id, :conversation_id,
                    NOW(), FALSE, NULL, NULL
                )
            """)

            await self.db.execute(
                insert_query,
                {
                    "user_id": user_id,
                    "insight_id": insight_id,
                    "conversation_id": conversation_id
                }
            )

            # Update surfaced_count and last_surfaced_at on the insight
            update_query = text("""
                UPDATE dream_insight
                SET surfaced_count = COALESCE(surfaced_count, 0) + 1,
                    last_surfaced_at = NOW(),
                    surfaced_at = COALESCE(surfaced_at, NOW())
                WHERE id = :insight_id
            """)

            await self.db.execute(update_query, {"insight_id": insight_id})
            await self.db.commit()

            logger.info(f"✅ Logged insight mention: {insight_id[:8]} for user {user_id[:8]}")

        except Exception as e:
            logger.error(f"Error logging insight mention: {e}")
            await self.db.rollback()

    async def log_engagement(
        self,
        user_id: str,
        insight_id: str,
        engagement_type: str
    ):
        """
        Log user engagement with a surfaced insight.

        Args:
            user_id: User identifier
            insight_id: Insight identifier
            engagement_type: Type of engagement (positive, neutral, negative, ignored)
        """
        try:
            query = text("""
                UPDATE insight_mention_log
                SET user_engaged = TRUE,
                    engagement_type = :engagement_type,
                    engaged_at = NOW()
                WHERE user_id = :user_id
                    AND insight_id = :insight_id
                    AND mentioned_at = (
                        SELECT MAX(mentioned_at)
                        FROM insight_mention_log
                        WHERE user_id = :user_id AND insight_id = :insight_id
                    )
            """)

            await self.db.execute(
                query,
                {
                    "user_id": user_id,
                    "insight_id": insight_id,
                    "engagement_type": engagement_type
                }
            )
            await self.db.commit()

            logger.info(f"✅ Logged engagement ({engagement_type}) for insight {insight_id[:8]}")

        except Exception as e:
            logger.error(f"Error logging engagement: {e}")
            await self.db.rollback()

    async def get_proactive_insights(
        self,
        user_id: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get proactive insights for morning brief or conversation lulls.
        These don't require semantic similarity - they're meant to be surfaced.

        Args:
            user_id: User identifier
            limit: Maximum number to return

        Returns:
            List of proactive insights ready to surface
        """
        try:
            query = text("""
                SELECT
                    di.id,
                    di.insight_type,
                    di.confidence,
                    di.title,
                    di.content,
                    di.evidence,
                    di.dream_date,
                    di.surfaced_count
                FROM dream_insight di
                WHERE di.user_id = :user_id
                    AND di.surface_strategy = 'proactive'
                    AND di.surfaced_count = 0  -- Never surfaced
                    AND (di.expiry_at IS NULL OR di.expiry_at > NOW())
                    AND di.confidence >= 0.5
                ORDER BY
                    di.confidence DESC,
                    di.dream_date DESC
                LIMIT :limit
            """)

            result = await self.db.execute(
                query,
                {"user_id": user_id, "limit": limit}
            )

            rows = result.fetchall()
            return [
                {
                    "id": row[0],
                    "insight_type": row[1],
                    "confidence": row[2],
                    "title": row[3],
                    "content": row[4],
                    "evidence": row[5],
                    "dream_date": row[6],
                    "surfaced_count": row[7]
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Error getting proactive insights: {e}")
            return []

    async def get_insights_for_injection(
        self,
        user_id: str,
        conversation_text: str,
        conversation_embedding: List[float],
        conversation_context: Dict[str, Any],
        conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Main entry point: Get formatted insight ready for injection into RAG.

        Args:
            user_id: User identifier
            conversation_text: Recent conversation text
            conversation_embedding: Vector embedding
            conversation_context: Context dictionary with:
                - turn_count: Number of turns in conversation
                - user_asking_question: Whether user is asking a question
                - insights_surfaced_count: How many insights surfaced this conversation
                - last_insight_turn: Last turn an insight was surfaced
            conversation_id: Conversation identifier

        Returns:
            Formatted insight text or None
        """
        # Get relevant insights
        insights = await self.get_relevant_insights(
            user_id=user_id,
            conversation_text=conversation_text,
            conversation_embedding=conversation_embedding,
            conversation_id=conversation_id,
            limit=10
        )

        if not insights:
            return None

        # Find best insight that should be surfaced
        best_insight = None
        best_score = 0.0
        best_reason = None

        for insight in insights:
            should_surface, reason, score = await self.should_surface_now(
                insight=insight,
                conversation_context=conversation_context
            )

            if should_surface and score > best_score:
                best_insight = insight
                best_score = score
                best_reason = reason

        if best_insight:
            # Log the mention
            await self.log_mention(
                user_id=user_id,
                insight_id=best_insight["id"],
                conversation_id=conversation_id or ""
            )

            # Choose injection style based on type
            style = "gentle"
            if best_insight.get("insight_type") == "unresolved_thread":
                style = "question"

            # Format for injection
            formatted = self.format_insight_injection(
                insight=best_insight,
                injection_style=style
            )

            logger.info(
                f"🎯 Surfacing insight: {best_insight['title'][:50]}... "
                f"(score: {best_score:.2f}, type: {best_insight['insight_type']}, reason: {best_reason})"
            )
            return formatted

        # No insights ready to surface
        return None

    async def get_relevant_patterns(
        self,
        user_id: str,
        conversation_text: str,
        conversation_embedding: Optional[List[float]] = None,
        limit: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Get confirmed patterns relevant to the current conversation context.

        Uses keyword matching and optional semantic similarity to find patterns
        that are contextually relevant to what the user is discussing.

        Args:
            user_id: User identifier
            conversation_text: Recent conversation text
            conversation_embedding: Optional vector embedding for semantic matching
            limit: Maximum patterns to return

        Returns:
            List of relevant patterns with narratives
        """
        try:
            # Determine relevant domains from conversation text
            text_lower = conversation_text.lower()
            relevant_domains = set()

            for domain, keywords in PATTERN_CONTEXT_KEYWORDS.items():
                if any(kw in text_lower for kw in keywords):
                    relevant_domains.add(domain)

            # If no domain matches, return empty
            if not relevant_domains:
                logger.debug("No relevant domains found in conversation for patterns")
                return []

            # Build domain filter for query
            domain_conditions = []
            for domain in relevant_domains:
                domain_conditions.append(f"metric_a LIKE '{domain}.%'")
                domain_conditions.append(f"metric_b LIKE '{domain}.%'")

            domain_filter = f"AND ({' OR '.join(domain_conditions)})" if domain_conditions else ""

            # Query confirmed patterns
            if conversation_embedding:
                # Use semantic similarity if embedding available
                query = text(f"""
                    SELECT
                        id, title, narrative, pattern_category,
                        metric_a, metric_b, correlation_coefficient,
                        confidence, temporal_lag_hours,
                        CASE
                            WHEN embedding IS NULL THEN 0.5
                            ELSE 1 - (embedding <=> CAST(:embedding AS vector))
                        END as similarity
                    FROM correlation_pattern
                    WHERE user_id = :user_id
                      AND status = 'confirmed'
                      AND confidence >= 0.6
                      {domain_filter}
                    ORDER BY
                        CASE WHEN embedding IS NOT NULL THEN 1 - (embedding <=> CAST(:embedding AS vector)) ELSE 0.5 END DESC,
                        confidence DESC
                    LIMIT :limit
                """)

                result = await self.db.execute(
                    query,
                    {
                        "user_id": user_id,
                        "embedding": str(conversation_embedding),
                        "limit": limit
                    }
                )
            else:
                # Fall back to confidence-based ranking
                query = text(f"""
                    SELECT
                        id, title, narrative, pattern_category,
                        metric_a, metric_b, correlation_coefficient,
                        confidence, temporal_lag_hours,
                        0.5 as similarity
                    FROM correlation_pattern
                    WHERE user_id = :user_id
                      AND status = 'confirmed'
                      AND confidence >= 0.6
                      {domain_filter}
                    ORDER BY confidence DESC
                    LIMIT :limit
                """)

                result = await self.db.execute(
                    query,
                    {"user_id": user_id, "limit": limit}
                )

            rows = result.fetchall()

            patterns = []
            for row in rows:
                patterns.append({
                    "id": str(row[0]),
                    "title": row[1],
                    "narrative": row[2],
                    "category": row[3],
                    "metric_a": row[4],
                    "metric_b": row[5],
                    "correlation": row[6],
                    "confidence": row[7],
                    "lag_hours": row[8],
                    "similarity": float(row[9]) if row[9] else 0.5
                })

            if patterns:
                logger.info(f"📊 Found {len(patterns)} relevant patterns for user {user_id[:8]}")

            return patterns

        except Exception as e:
            logger.error(f"Error getting relevant patterns: {e}", exc_info=True)
            return []

    def format_pattern_injection(self, pattern: Dict[str, Any]) -> str:
        """
        Format a pattern for natural injection into conversation.

        Args:
            pattern: Pattern dictionary with title, narrative, correlation, etc.

        Returns:
            Formatted string for injection
        """
        narrative = pattern.get("narrative")
        if narrative:
            # Narrative is already formatted for natural language
            return f"Based on your data: {narrative}"

        # Fallback to building from components
        title = pattern.get("title", "Pattern")
        correlation = pattern.get("correlation", 0)
        direction = "positive" if correlation > 0 else "negative"
        strength = abs(correlation)

        if strength > 0.7:
            strength_word = "strong"
        elif strength > 0.4:
            strength_word = "moderate"
        else:
            strength_word = "mild"

        return f"I've noticed a {strength_word} {direction} pattern: {title}"

    async def get_combined_context(
        self,
        user_id: str,
        conversation_text: str,
        conversation_embedding: List[float],
        conversation_context: Dict[str, Any],
        conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Get combined insights and patterns for injection into RAG context.

        This method combines dream insights with cross-domain patterns
        to provide richer contextual information to Sara.

        Args:
            user_id: User identifier
            conversation_text: Recent conversation text
            conversation_embedding: Vector embedding
            conversation_context: Context dictionary
            conversation_id: Conversation identifier

        Returns:
            Combined formatted context string or None
        """
        context_parts = []

        # Get dream insight (existing logic)
        insight_text = await self.get_insights_for_injection(
            user_id=user_id,
            conversation_text=conversation_text,
            conversation_embedding=conversation_embedding,
            conversation_context=conversation_context,
            conversation_id=conversation_id
        )

        if insight_text:
            context_parts.append(insight_text)

        # Get relevant patterns
        patterns = await self.get_relevant_patterns(
            user_id=user_id,
            conversation_text=conversation_text,
            conversation_embedding=conversation_embedding,
            limit=2
        )

        for pattern in patterns:
            pattern_text = self.format_pattern_injection(pattern)
            if pattern_text:
                context_parts.append(pattern_text)

        if not context_parts:
            return None

        # Combine with separator
        return "\n\n".join(context_parts)
