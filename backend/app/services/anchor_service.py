"""
Anchor Service
Generates, stores, and manages analogy anchors that bridge new learning concepts
to David's known domains. Uses LLM to generate analogies and the PKG for context.
"""
import logging
import uuid
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.anchor_point import AnchorPoint
from app.models.known_domain import KnownDomain
from app.models.learning import LearningTopic

logger = logging.getLogger(__name__)


class AnchorService:
    """Service for generating and managing analogy anchor points"""

    async def generate_anchors(
        self,
        topic_id: str,
        user_id: str,
        db: Session,
        regenerate: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Generate 2-3 analogy anchors for a topic based on David's known domains.

        Args:
            topic_id: Learning topic to generate anchors for
            user_id: User ID
            db: Database session
            regenerate: If True, generate new anchors even if some exist

        Returns:
            List of anchor point dicts
        """
        try:
            from app.core.llm import llm_client

            # Get the topic
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return []

            # Check existing non-rejected anchors
            if not regenerate:
                existing = db.query(AnchorPoint).filter(
                    AnchorPoint.topic_id == topic_id,
                    AnchorPoint.user_id == user_id,
                    AnchorPoint.rejected == False
                ).count()
                if existing >= 2:
                    return [a.to_dict() for a in db.query(AnchorPoint).filter(
                        AnchorPoint.topic_id == topic_id,
                        AnchorPoint.user_id == user_id,
                        AnchorPoint.rejected == False
                    ).all()]

            # Get known domains
            domains = db.query(KnownDomain).filter(
                KnownDomain.user_id == user_id
            ).all()

            if not domains:
                logger.info("No known domains found — skipping anchor generation")
                return []

            # Build domain context
            domain_context = ""
            for d in domains:
                concepts = ", ".join(d.key_concepts[:8]) if d.key_concepts else "general knowledge"
                domain_context += f"- {d.domain_name} ({d.proficiency}): {concepts}\n"

            prompt = f"""David is learning about "{topic.title}".
{f'Description: {topic.description}' if topic.description else ''}

David already knows these domains well:
{domain_context}

Generate 2-3 analogy anchors that connect "{topic.title}" to David's existing knowledge.
Each anchor should:
1. Pick a specific concept from one of David's known domains
2. Explain how it maps to a concept in the new topic
3. Note where the analogy breaks down (so David doesn't over-apply it)

Output as JSON:
{{
  "anchors": [
    {{
      "anchor_concept": "The analogy concept name",
      "anchor_domain": "Which known domain it comes from",
      "bridge_description": "How the analogy works: 'Think of X like Y because Z. The analogy breaks down when...'",
      "confidence": 0.7
    }}
  ]
}}

Return ONLY valid JSON. Be specific and practical — avoid vague analogies."""

            response = await llm_client.generate(prompt=prompt, max_tokens=500)

            if not response:
                return []

            # Parse response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return []

            data = json.loads(json_match.group())
            anchors_data = data.get("anchors", [])

            # Store anchor points
            created_anchors = []
            for anchor_data in anchors_data[:3]:
                anchor = AnchorPoint(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    topic_id=topic_id,
                    anchor_concept=anchor_data.get("anchor_concept", ""),
                    anchor_domain=anchor_data.get("anchor_domain", ""),
                    bridge_description=anchor_data.get("bridge_description", ""),
                    confidence=min(max(anchor_data.get("confidence", 0.5), 0.0), 1.0),
                )
                db.add(anchor)
                created_anchors.append(anchor)

            db.commit()
            return [a.to_dict() for a in created_anchors]

        except Exception as e:
            logger.error(f"Failed to generate anchors for topic {topic_id}: {e}")
            db.rollback()
            return []

    async def get_active_anchors(
        self,
        topic_id: str,
        user_id: str,
        db: Session
    ) -> List[Dict[str, Any]]:
        """Get non-rejected anchors for a topic, sorted by confidence and validation"""
        anchors = db.query(AnchorPoint).filter(
            AnchorPoint.topic_id == topic_id,
            AnchorPoint.user_id == user_id,
            AnchorPoint.rejected == False
        ).order_by(
            AnchorPoint.validated.desc(),
            AnchorPoint.confidence.desc()
        ).all()

        return [a.to_dict() for a in anchors]

    async def validate_anchor(
        self,
        anchor_id: str,
        user_id: str,
        db: Session,
        is_valid: bool
    ) -> Optional[Dict[str, Any]]:
        """Validate or reject an anchor point"""
        anchor = db.query(AnchorPoint).filter(
            AnchorPoint.id == anchor_id,
            AnchorPoint.user_id == user_id
        ).first()

        if not anchor:
            return None

        if is_valid:
            anchor.validated = True
            anchor.rejected = False
            anchor.confidence = min(anchor.confidence + 0.2, 1.0)
        else:
            anchor.rejected = True
            anchor.validated = False

        db.commit()
        return anchor.to_dict()


# Singleton instance
anchor_service = AnchorService()
