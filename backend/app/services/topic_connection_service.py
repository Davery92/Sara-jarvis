"""
Topic Connection Service
Manages semantic relationships between learning topics, including
automatic discovery of connections via embedding similarity.
"""
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.learning import LearningTopic, TopicConnection, TopicSource, SourceChunk
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class TopicConnectionService:
    """Service for managing cross-topic semantic relationships"""

    # Connection types with descriptions
    CONNECTION_TYPES = {
        "prerequisite": "Understanding this topic requires knowledge of the other",
        "related": "Topics share common concepts or themes",
        "builds_on": "This topic extends or deepens the other",
        "contrasts": "Topics represent different approaches or opposing views",
        "applies_to": "This topic is a practical application of the other"
    }

    # Similarity thresholds for auto-detection
    MIN_SIMILARITY_THRESHOLD = 0.65
    STRONG_SIMILARITY_THRESHOLD = 0.80

    async def create_connection(
        self,
        user_id: str,
        source_topic_id: str,
        target_topic_id: str,
        connection_type: str,
        db: Session,
        description: Optional[str] = None,
        strength: float = 0.5,
        auto_generated: bool = False
    ) -> Dict[str, Any]:
        """
        Create a connection between two topics.

        Args:
            user_id: User ID
            source_topic_id: Source topic ID
            target_topic_id: Target topic ID
            connection_type: Type of relationship
            db: Database session
            description: Optional description
            strength: Connection strength (0.0-1.0)
            auto_generated: Whether this was auto-detected

        Returns:
            Created connection dict or error
        """
        try:
            # Validate connection type
            if connection_type not in self.CONNECTION_TYPES:
                return {
                    "status": "error",
                    "error": f"Invalid connection type. Valid types: {list(self.CONNECTION_TYPES.keys())}"
                }

            # Verify both topics exist and belong to user
            source_topic = db.query(LearningTopic).filter(
                LearningTopic.id == source_topic_id,
                LearningTopic.user_id == user_id
            ).first()

            target_topic = db.query(LearningTopic).filter(
                LearningTopic.id == target_topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not source_topic:
                return {"status": "error", "error": "Source topic not found"}
            if not target_topic:
                return {"status": "error", "error": "Target topic not found"}
            if source_topic_id == target_topic_id:
                return {"status": "error", "error": "Cannot connect a topic to itself"}

            # Check if connection already exists
            existing = db.query(TopicConnection).filter(
                TopicConnection.user_id == user_id,
                TopicConnection.source_topic_id == source_topic_id,
                TopicConnection.target_topic_id == target_topic_id,
                TopicConnection.connection_type == connection_type
            ).first()

            if existing:
                return {
                    "status": "exists",
                    "connection": existing.to_dict(),
                    "message": "Connection already exists"
                }

            # Create connection
            connection = TopicConnection(
                id=str(uuid.uuid4()),
                user_id=user_id,
                source_topic_id=source_topic_id,
                target_topic_id=target_topic_id,
                connection_type=connection_type,
                strength=min(1.0, max(0.0, strength)),
                description=description,
                auto_generated=auto_generated,
                confirmed=not auto_generated  # Manual connections are auto-confirmed
            )

            db.add(connection)
            db.commit()

            return {
                "status": "created",
                "connection": connection.to_dict(),
                "source_topic": source_topic.title,
                "target_topic": target_topic.title
            }

        except Exception as e:
            logger.error(f"Error creating topic connection: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}

    async def get_connections(
        self,
        user_id: str,
        topic_id: str,
        db: Session,
        include_unconfirmed: bool = False
    ) -> Dict[str, Any]:
        """
        Get all connections for a topic (both outgoing and incoming).

        Args:
            user_id: User ID
            topic_id: Topic ID
            db: Database session
            include_unconfirmed: Include auto-generated but unconfirmed connections

        Returns:
            Dict with outgoing and incoming connections
        """
        try:
            base_query = db.query(TopicConnection).filter(
                TopicConnection.user_id == user_id
            )

            if not include_unconfirmed:
                base_query = base_query.filter(
                    or_(
                        TopicConnection.auto_generated == False,
                        TopicConnection.confirmed == True
                    )
                )

            # Get outgoing connections (this topic -> other topics)
            outgoing = base_query.filter(
                TopicConnection.source_topic_id == topic_id
            ).all()

            # Get incoming connections (other topics -> this topic)
            incoming = base_query.filter(
                TopicConnection.target_topic_id == topic_id
            ).all()

            # Enrich with topic titles
            topic_ids = set()
            for conn in outgoing + incoming:
                topic_ids.add(conn.source_topic_id)
                topic_ids.add(conn.target_topic_id)

            topics = {t.id: t for t in db.query(LearningTopic).filter(
                LearningTopic.id.in_(topic_ids)
            ).all()}

            outgoing_enriched = []
            for conn in outgoing:
                conn_dict = conn.to_dict()
                conn_dict["target_topic_title"] = topics.get(conn.target_topic_id, {}).title if topics.get(conn.target_topic_id) else "Unknown"
                outgoing_enriched.append(conn_dict)

            incoming_enriched = []
            for conn in incoming:
                conn_dict = conn.to_dict()
                conn_dict["source_topic_title"] = topics.get(conn.source_topic_id, {}).title if topics.get(conn.source_topic_id) else "Unknown"
                incoming_enriched.append(conn_dict)

            return {
                "topic_id": topic_id,
                "outgoing": outgoing_enriched,
                "incoming": incoming_enriched,
                "total_connections": len(outgoing) + len(incoming)
            }

        except Exception as e:
            logger.error(f"Error getting topic connections: {e}")
            return {"topic_id": topic_id, "outgoing": [], "incoming": [], "error": str(e)}

    async def discover_connections(
        self,
        user_id: str,
        topic_id: str,
        db: Session,
        auto_create: bool = False
    ) -> Dict[str, Any]:
        """
        Discover potential connections for a topic using semantic similarity.

        Args:
            user_id: User ID
            topic_id: Topic ID to find connections for
            db: Database session
            auto_create: Automatically create discovered connections

        Returns:
            List of potential connections with similarity scores
        """
        try:
            # Get the target topic
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return {"status": "error", "error": "Topic not found"}

            # Get all other topics for this user
            other_topics = db.query(LearningTopic).filter(
                LearningTopic.user_id == user_id,
                LearningTopic.id != topic_id,
                LearningTopic.status == "active"
            ).all()

            if not other_topics:
                return {
                    "topic_id": topic_id,
                    "suggestions": [],
                    "message": "No other topics to compare"
                }

            # Get embeddings for chunks from the source topic
            source_chunks = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic_id
            ).limit(20).all()

            if not source_chunks:
                # Fall back to title/description embedding
                text_to_embed = f"{topic.title}. {topic.description or ''}"
                source_embedding = await embedding_service.generate_embedding(text_to_embed)
                if not source_embedding:
                    return {"topic_id": topic_id, "suggestions": [], "error": "Could not generate embedding"}
                source_embeddings = [source_embedding]
            else:
                source_embeddings = [chunk.embedding for chunk in source_chunks if chunk.embedding is not None]

            if not source_embeddings:
                return {"topic_id": topic_id, "suggestions": [], "error": "No embeddings found"}

            # Find similar topics
            suggestions = []

            for other_topic in other_topics:
                # Get chunks from the other topic
                other_chunks = db.query(SourceChunk).join(TopicSource).filter(
                    TopicSource.topic_id == other_topic.id
                ).limit(20).all()

                if other_chunks:
                    other_embeddings = [c.embedding for c in other_chunks if c.embedding is not None]
                else:
                    # Fall back to title/description
                    text_to_embed = f"{other_topic.title}. {other_topic.description or ''}"
                    other_embedding = await embedding_service.generate_embedding(text_to_embed)
                    if other_embedding:
                        other_embeddings = [other_embedding]
                    else:
                        continue

                if not other_embeddings:
                    continue

                # Calculate average similarity between topics
                max_similarity = 0.0
                for src_emb in source_embeddings:
                    for other_emb in other_embeddings:
                        similarity = self._cosine_similarity(src_emb, other_emb)
                        max_similarity = max(max_similarity, similarity)

                if max_similarity >= self.MIN_SIMILARITY_THRESHOLD:
                    # Check if connection already exists
                    existing = db.query(TopicConnection).filter(
                        TopicConnection.user_id == user_id,
                        or_(
                            and_(
                                TopicConnection.source_topic_id == topic_id,
                                TopicConnection.target_topic_id == other_topic.id
                            ),
                            and_(
                                TopicConnection.source_topic_id == other_topic.id,
                                TopicConnection.target_topic_id == topic_id
                            )
                        )
                    ).first()

                    suggestion = {
                        "topic_id": other_topic.id,
                        "topic_title": other_topic.title,
                        "similarity": round(max_similarity, 3),
                        "strength": "strong" if max_similarity >= self.STRONG_SIMILARITY_THRESHOLD else "moderate",
                        "existing_connection": existing.to_dict() if existing else None,
                        "suggested_type": "related"
                    }

                    suggestions.append(suggestion)

            # Sort by similarity
            suggestions.sort(key=lambda x: x["similarity"], reverse=True)

            # Auto-create strong connections if requested
            created_connections = []
            if auto_create:
                for suggestion in suggestions:
                    if suggestion["similarity"] >= self.STRONG_SIMILARITY_THRESHOLD and not suggestion["existing_connection"]:
                        result = await self.create_connection(
                            user_id=user_id,
                            source_topic_id=topic_id,
                            target_topic_id=suggestion["topic_id"],
                            connection_type="related",
                            db=db,
                            strength=suggestion["similarity"],
                            auto_generated=True
                        )
                        if result.get("status") == "created":
                            created_connections.append(result["connection"])

            return {
                "topic_id": topic_id,
                "topic_title": topic.title,
                "suggestions": suggestions[:10],  # Top 10
                "created_connections": created_connections if auto_create else None
            }

        except Exception as e:
            logger.error(f"Error discovering connections: {e}")
            return {"topic_id": topic_id, "suggestions": [], "error": str(e)}

    async def confirm_connection(
        self,
        user_id: str,
        connection_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """Confirm an auto-generated connection"""
        try:
            connection = db.query(TopicConnection).filter(
                TopicConnection.id == connection_id,
                TopicConnection.user_id == user_id
            ).first()

            if not connection:
                return {"status": "error", "error": "Connection not found"}

            connection.confirmed = True
            db.commit()

            return {"status": "confirmed", "connection": connection.to_dict()}

        except Exception as e:
            logger.error(f"Error confirming connection: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}

    async def delete_connection(
        self,
        user_id: str,
        connection_id: str,
        db: Session
    ) -> Dict[str, Any]:
        """Delete a topic connection"""
        try:
            connection = db.query(TopicConnection).filter(
                TopicConnection.id == connection_id,
                TopicConnection.user_id == user_id
            ).first()

            if not connection:
                return {"status": "error", "error": "Connection not found"}

            db.delete(connection)
            db.commit()

            return {"status": "deleted", "connection_id": connection_id}

        except Exception as e:
            logger.error(f"Error deleting connection: {e}")
            db.rollback()
            return {"status": "error", "error": str(e)}

    async def get_topic_graph(
        self,
        user_id: str,
        db: Session,
        include_unconfirmed: bool = False
    ) -> Dict[str, Any]:
        """
        Get all topics and connections as a graph structure for visualization.

        Returns:
            Dict with nodes (topics) and edges (connections)
        """
        try:
            # Get all topics
            topics = db.query(LearningTopic).filter(
                LearningTopic.user_id == user_id,
                LearningTopic.status == "active"
            ).all()

            # Get all connections
            conn_query = db.query(TopicConnection).filter(
                TopicConnection.user_id == user_id
            )

            if not include_unconfirmed:
                conn_query = conn_query.filter(
                    or_(
                        TopicConnection.auto_generated == False,
                        TopicConnection.confirmed == True
                    )
                )

            connections = conn_query.all()

            nodes = [
                {
                    "id": t.id,
                    "label": t.title,
                    "mastery": t.mastery_level,
                    "priority": t.priority,
                    "status": t.status
                }
                for t in topics
            ]

            edges = [
                {
                    "id": c.id,
                    "source": c.source_topic_id,
                    "target": c.target_topic_id,
                    "type": c.connection_type,
                    "strength": c.strength,
                    "auto_generated": c.auto_generated,
                    "confirmed": c.confirmed
                }
                for c in connections
            ]

            return {
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges)
            }

        except Exception as e:
            logger.error(f"Error getting topic graph: {e}")
            return {"nodes": [], "edges": [], "error": str(e)}

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)


# Singleton instance
topic_connection_service = TopicConnectionService()
