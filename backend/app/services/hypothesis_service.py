"""
Hypothesis Service

This service manages Sara's hypotheses/beliefs about David.
Sara's beliefs become explicit, trackable, and legible:
1. Extract hypotheses from conversations
2. Add/update evidence for existing hypotheses
3. Track confidence evolution
4. Provide user model queries
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, desc
import logging
import json

from app.models.cognitive import Hypothesis

logger = logging.getLogger(__name__)


class HypothesisService:
    """
    Service for managing Sara's hypotheses about David.
    Makes Sara's beliefs explicit, trackable, and legible.
    """

    # Confidence thresholds
    CONFIDENCE_CONFIRMED = 0.85
    CONFIDENCE_REFUTED = 0.15
    CONFIDENCE_INITIAL = 0.3

    def __init__(self):
        self._llm_client = None
        self._embedding_service = None

    def _get_llm_client(self):
        """Lazy-load background LLM client for hypothesis extraction"""
        if self._llm_client:
            return self._llm_client
        try:
            from app.core.llm import get_background_llm_client
            self._llm_client = get_background_llm_client()
            return self._llm_client
        except Exception as e:
            logger.error(f"Failed to initialize background LLM client: {e}")
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

    async def extract_hypotheses_from_conversation(
        self,
        db: Session,
        conversation_episodes: List[Dict]
    ) -> List[Hypothesis]:
        """Extract potential hypotheses from a conversation."""

        llm = self._get_llm_client()
        if not llm:
            return []

        conversation_text = "\n".join([
            f"{ep.get('role', 'unknown')}: {ep.get('content', '')[:500]}"
            for ep in conversation_episodes
        ])

        prompt = f"""Analyze this conversation and identify facts or patterns about David that Sara should track as hypotheses.

Conversation:
{conversation_text}

Look for:
- Goals David is working toward
- Preferences he's expressed or demonstrated
- Patterns in his behavior or interests
- Facts about his life, work, or circumstances
- Emotional patterns or tendencies

For each hypothesis, provide ONLY valid JSON:
{{
    "hypotheses": [
        {{
            "statement": "Clear statement of what Sara believes about David",
            "domain": "health|work|personal|technical|habits|relationships|interests|other",
            "confidence": 0.0-1.0 based on strength of evidence,
            "evidence_quote": "Specific quote or observation that supports this"
        }}
    ]
}}

Only include hypotheses with actual evidence from this conversation. Be specific, not vague.
If no clear hypotheses can be formed, return {{"hypotheses": []}}"""

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are extracting hypotheses about David. Respond with ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            response_text = result["choices"][0]["message"]["content"].strip()
            # Handle markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            parsed = json.loads(response_text)

            new_hypotheses = []
            embedding_fn = self._get_embedding_service()

            for h in parsed.get("hypotheses", []):
                # Check if this hypothesis already exists
                existing = await self._find_similar_hypothesis(db, h["statement"])

                if existing:
                    # Add evidence to existing hypothesis
                    await self.add_evidence(
                        db=db,
                        hypothesis_id=existing.id,
                        evidence_type="for",
                        quote=h.get("evidence_quote", ""),
                        episode_ids=[ep.get("id") for ep in conversation_episodes if ep.get("id")]
                    )
                else:
                    # Create new hypothesis
                    hypothesis = Hypothesis(
                        statement=h["statement"],
                        domain=h.get("domain", "other"),
                        confidence=h.get("confidence", self.CONFIDENCE_INITIAL),
                        evidence_for=[{
                            "quote": h.get("evidence_quote", ""),
                            "episode_ids": [ep.get("id") for ep in conversation_episodes if ep.get("id")],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "weight": h.get("confidence", 0.3)
                        }]
                    )

                    # Generate embedding
                    if embedding_fn:
                        try:
                            hypothesis.embedding = await embedding_fn(h["statement"])
                        except Exception as e:
                            logger.warning(f"Failed to generate embedding for hypothesis: {e}")

                    db.add(hypothesis)
                    new_hypotheses.append(hypothesis)

            db.commit()
            logger.info(f"Extracted {len(new_hypotheses)} new hypotheses from conversation")
            return new_hypotheses

        except Exception as e:
            logger.error(f"Failed to extract hypotheses: {e}")
            return []

    async def _find_similar_hypothesis(
        self,
        db: Session,
        statement: str,
        similarity_threshold: float = 0.85
    ) -> Optional[Hypothesis]:
        """Find an existing hypothesis that's semantically similar."""

        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            return None

        try:
            statement_embedding = await embedding_fn(statement)

            from sqlalchemy import text

            # Use L2 distance - smaller is more similar
            # Convert threshold: cosine_sim 0.85 roughly corresponds to L2 distance < 0.55
            l2_threshold = 2 * (1 - similarity_threshold)  # Approximate conversion

            sql = text("""
                SELECT id
                FROM hypothesis
                WHERE status IN ('active', 'confirmed')
                AND embedding IS NOT NULL
                AND embedding <-> :query_embedding < :threshold
                ORDER BY embedding <-> :query_embedding ASC
                LIMIT 1
            """)

            result = db.execute(sql, {
                "query_embedding": str(statement_embedding),
                "threshold": l2_threshold
            })
            row = result.fetchone()

            if row:
                return db.query(Hypothesis).filter(Hypothesis.id == row[0]).first()

        except Exception as e:
            logger.warning(f"Failed to find similar hypothesis: {e}")

        return None

    async def add_evidence(
        self,
        db: Session,
        hypothesis_id: str,
        evidence_type: str,  # "for" or "against"
        quote: str,
        episode_ids: List[str],
        weight: float = 0.5
    ):
        """Add evidence to an existing hypothesis."""

        hypothesis = db.query(Hypothesis).filter(Hypothesis.id == hypothesis_id).first()

        if not hypothesis:
            return

        evidence_entry = {
            "quote": quote,
            "episode_ids": episode_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "weight": weight
        }

        if evidence_type == "for":
            evidence_list = hypothesis.evidence_for or []
            evidence_list.append(evidence_entry)
            hypothesis.evidence_for = evidence_list
        else:
            evidence_list = hypothesis.evidence_against or []
            evidence_list.append(evidence_entry)
            hypothesis.evidence_against = evidence_list

        # Recalculate confidence
        hypothesis.confidence = self._calculate_confidence(
            hypothesis.evidence_for or [],
            hypothesis.evidence_against or []
        )

        # Update status based on confidence
        if hypothesis.confidence >= self.CONFIDENCE_CONFIRMED:
            hypothesis.status = "confirmed"
        elif hypothesis.confidence <= self.CONFIDENCE_REFUTED:
            hypothesis.status = "refuted"
        else:
            hypothesis.status = "active"

        hypothesis.last_updated = datetime.now(timezone.utc)
        hypothesis.last_evidence_at = datetime.now(timezone.utc)

        db.commit()
        logger.info(f"Added {evidence_type} evidence to hypothesis {hypothesis_id}, new confidence: {hypothesis.confidence:.2f}")

    def _calculate_confidence(
        self,
        evidence_for: List[Dict],
        evidence_against: List[Dict]
    ) -> float:
        """Calculate confidence based on evidence."""

        def time_weight(timestamp_str: str) -> float:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - ts).days
                # Half-life of 30 days
                return 0.5 ** (age_days / 30)
            except:
                return 0.5

        total_for = sum(
            e.get("weight", 0.5) * time_weight(e.get("timestamp", ""))
            for e in evidence_for
        )
        total_against = sum(
            e.get("weight", 0.5) * time_weight(e.get("timestamp", ""))
            for e in evidence_against
        )

        if total_for + total_against == 0:
            return self.CONFIDENCE_INITIAL

        # Bayesian-ish update
        confidence = total_for / (total_for + total_against)

        # Clamp to reasonable range
        return max(0.05, min(0.95, confidence))

    async def get_relevant_hypotheses(
        self,
        db: Session,
        query: str,
        domain: Optional[str] = None,
        min_confidence: float = 0.2,
        limit: int = 5
    ) -> List[Hypothesis]:
        """Get hypotheses relevant to the current context."""

        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            # Fallback to non-semantic query
            query_obj = db.query(Hypothesis).filter(
                and_(
                    Hypothesis.status.in_(['active', 'confirmed']),
                    Hypothesis.confidence >= min_confidence
                )
            )
            if domain:
                query_obj = query_obj.filter(Hypothesis.domain == domain)
            return query_obj.order_by(desc(Hypothesis.confidence)).limit(limit).all()

        try:
            query_embedding = await embedding_fn(query)

            from sqlalchemy import text

            sql = text("""
                SELECT id, embedding <-> :query_embedding AS distance
                FROM hypothesis
                WHERE status IN ('active', 'confirmed')
                AND confidence >= :min_confidence
                AND embedding IS NOT NULL
                """ + (f"AND domain = :domain" if domain else "") + """
                ORDER BY distance ASC
                LIMIT :limit
            """)

            params = {
                "query_embedding": str(query_embedding),
                "min_confidence": min_confidence,
                "limit": limit
            }
            if domain:
                params["domain"] = domain

            result = db.execute(sql, params)
            rows = result.fetchall()

            hypotheses = []
            for row in rows:
                hypothesis = db.query(Hypothesis).filter(Hypothesis.id == row[0]).first()
                if hypothesis:
                    hypotheses.append(hypothesis)

            return hypotheses

        except Exception as e:
            logger.error(f"Failed to get relevant hypotheses: {e}")
            return []

    async def get_user_model_summary(self, db: Session) -> Dict[str, Any]:
        """Get a summary of Sara's current model of the user."""

        hypotheses = db.query(Hypothesis).filter(
            Hypothesis.status.in_(['active', 'confirmed'])
        ).order_by(desc(Hypothesis.confidence)).all()

        high_confidence = [h for h in hypotheses if h.confidence >= 0.8]
        medium_confidence = [h for h in hypotheses if 0.5 <= h.confidence < 0.8]
        forming = [h for h in hypotheses if h.confidence < 0.5]

        return {
            "high_confidence": [
                {"statement": h.statement, "domain": h.domain, "confidence": h.confidence}
                for h in high_confidence
            ],
            "medium_confidence": [
                {"statement": h.statement, "domain": h.domain, "confidence": h.confidence}
                for h in medium_confidence
            ],
            "forming": [
                {"statement": h.statement, "domain": h.domain, "confidence": h.confidence}
                for h in forming[:10]  # Limit to top 10 forming hypotheses
            ],
            "total_hypotheses": len(hypotheses),
            "domains_covered": list(set(h.domain for h in hypotheses))
        }

    async def mark_hypothesis_useful(self, db: Session, hypothesis_id: str):
        """Track when a hypothesis was useful in generating a response."""

        hypothesis = db.query(Hypothesis).filter(Hypothesis.id == hypothesis_id).first()

        if hypothesis:
            hypothesis.times_useful += 1
            hypothesis.last_updated = datetime.now(timezone.utc)
            db.commit()

    async def decay_stale_hypotheses(self, db: Session, stale_days: int = 60):
        """Reduce confidence of hypotheses with no recent evidence."""

        stale_threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)

        hypotheses = db.query(Hypothesis).filter(
            and_(
                Hypothesis.status == 'active',
                or_(
                    Hypothesis.last_evidence_at < stale_threshold,
                    Hypothesis.last_evidence_at.is_(None)
                )
            )
        ).all()

        for h in hypotheses:
            # Apply decay
            h.confidence *= 0.9  # 10% decay
            if h.confidence < 0.15:
                h.status = 'stale'
            h.last_updated = datetime.now(timezone.utc)

        db.commit()
        logger.info(f"Decayed {len(hypotheses)} stale hypotheses")

    async def get_hypothesis_by_id(self, db: Session, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a specific hypothesis by ID."""
        return db.query(Hypothesis).filter(Hypothesis.id == hypothesis_id).first()

    async def refute_hypothesis(
        self,
        db: Session,
        hypothesis_id: str,
        reason: str,
        episode_ids: Optional[List[str]] = None
    ):
        """Explicitly refute a hypothesis."""

        hypothesis = db.query(Hypothesis).filter(Hypothesis.id == hypothesis_id).first()

        if hypothesis:
            await self.add_evidence(
                db=db,
                hypothesis_id=hypothesis_id,
                evidence_type="against",
                quote=reason,
                episode_ids=episode_ids or [],
                weight=0.8  # Strong weight for explicit refutation
            )


# Global service instance
hypothesis_service = HypothesisService()
