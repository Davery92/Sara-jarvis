"""
Memory Consolidation Service
Consolidates low-importance old memories into summaries
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class MemoryConsolidationService:
    """Service for consolidating low-importance memories"""

    def __init__(self, db: Session, llm_client=None):
        self.db = db
        self.llm_client = llm_client

    async def consolidate_memories(
        self,
        user_id: str,
        importance_threshold: float = 0.1,
        age_days: int = 180,
        batch_size: int = 20
    ) -> Dict[str, Any]:
        """
        Consolidate low-importance old memories

        Args:
            user_id: User ID
            importance_threshold: Importance below this gets consolidated
            age_days: Minimum age in days
            batch_size: Memories per consolidation batch

        Returns:
            Consolidation statistics
        """
        try:
            logger.info(f"🗜️  Starting memory consolidation for user {user_id}")

            # Find candidate memories
            candidates = await self._find_consolidation_candidates(
                user_id,
                importance_threshold,
                age_days,
                batch_size * 5  # Get 5x batch size to cluster
            )

            if not candidates:
                logger.info("No memories need consolidation")
                return {
                    "consolidated_count": 0,
                    "summaries_created": 0,
                    "space_saved": 0
                }

            # Cluster by topic/time
            clusters = await self._cluster_memories(candidates, batch_size)

            consolidated_count = 0
            summaries_created = 0
            space_saved = 0

            # Consolidate each cluster
            for cluster in clusters:
                try:
                    summary = await self._create_consolidation_summary(cluster)

                    if summary:
                        # Mark memories as consolidated
                        memory_ids = [m["id"] for m in cluster]
                        await self._mark_as_consolidated(memory_ids, summary["id"])

                        consolidated_count += len(cluster)
                        summaries_created += 1
                        space_saved += sum(len(m["content"]) for m in cluster)

                except Exception as e:
                    logger.error(f"Error consolidating cluster: {e}")
                    continue

            self.db.commit()

            logger.info(f"✅ Consolidated {consolidated_count} memories into {summaries_created} summaries")

            return {
                "consolidated_count": consolidated_count,
                "summaries_created": summaries_created,
                "space_saved": space_saved,
                "candidates_found": len(candidates)
            }

        except Exception as e:
            logger.error(f"Error in memory consolidation: {e}")
            self.db.rollback()
            return {
                "error": str(e),
                "consolidated_count": 0
            }

    async def _find_consolidation_candidates(
        self,
        user_id: str,
        threshold: float,
        age_days: int,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Find memories that should be consolidated"""
        try:
            query = text("""
                SELECT
                    id,
                    content,
                    importance,
                    created_at,
                    topics,
                    emotional_tone
                FROM episode
                WHERE user_id = :user_id
                AND importance < :threshold
                AND created_at < NOW() - INTERVAL ':age_days days'
                AND consolidated = FALSE
                AND LENGTH(content) > 20
                ORDER BY created_at ASC
                LIMIT :limit
            """)

            result = self.db.execute(query, {
                "user_id": user_id,
                "threshold": threshold,
                "age_days": age_days,
                "limit": limit
            })

            candidates = []
            for row in result.fetchall():
                candidates.append({
                    "id": row.id,
                    "content": row.content,
                    "importance": row.importance,
                    "created_at": row.created_at,
                    "topics": json.loads(row.topics) if row.topics else [],
                    "emotional_tone": json.loads(row.emotional_tone) if row.emotional_tone else {}
                })

            return candidates

        except Exception as e:
            logger.error(f"Error finding candidates: {e}")
            return []

    async def _cluster_memories(
        self,
        memories: List[Dict[str, Any]],
        batch_size: int
    ) -> List[List[Dict[str, Any]]]:
        """
        Cluster memories by topic and time proximity

        Args:
            memories: List of memory dictionaries
            batch_size: Target cluster size

        Returns:
            List of memory clusters
        """
        # Simple time-based clustering for now
        # More sophisticated topic clustering could be added
        clusters = []
        current_cluster = []

        for memory in memories:
            current_cluster.append(memory)

            if len(current_cluster) >= batch_size:
                clusters.append(current_cluster)
                current_cluster = []

        # Add remaining
        if current_cluster:
            clusters.append(current_cluster)

        return clusters

    async def _create_consolidation_summary(
        self,
        cluster: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Create a summary episode from a cluster of memories

        Args:
            cluster: List of memories to consolidate

        Returns:
            Summary episode data or None
        """
        try:
            if not cluster:
                return None

            # Extract information
            start_date = min(m["created_at"] for m in cluster)
            end_date = max(m["created_at"] for m in cluster)
            contents = [m["content"] for m in cluster]

            # Generate summary using LLM if available
            if self.llm_client:
                summary_content = await self._generate_llm_summary(cluster)
            else:
                # Fallback: simple text summary
                summary_content = f"Summary of {len(cluster)} memories from {start_date.date()} to {end_date.date()}: " + " | ".join(contents[:5])

            # Extract combined topics
            all_topics = set()
            for m in cluster:
                all_topics.update(m.get("topics", []))

            # Create summary episode
            user_id = cluster[0].get("user_id")  # Assume all from same user

            insert_query = text("""
                INSERT INTO episode (
                    user_id,
                    role,
                    content,
                    importance,
                    memory_type,
                    source,
                    topics,
                    consolidated,
                    created_at
                )
                VALUES (
                    :user_id,
                    'system',
                    :content,
                    :importance,
                    'consolidation_summary',
                    'memory_consolidation',
                    :topics,
                    TRUE,
                    :created_at
                )
                RETURNING id
            """)

            # Calculate average importance for summary
            avg_importance = sum(m["importance"] for m in cluster) / len(cluster)

            result = self.db.execute(insert_query, {
                "user_id": user_id,
                "content": summary_content,
                "importance": avg_importance * 1.2,  # Slight boost for summary
                "topics": json.dumps(list(all_topics)),
                "created_at": end_date
            })

            summary_id = result.fetchone()[0]

            logger.info(f"Created consolidation summary {summary_id} from {len(cluster)} memories")

            return {
                "id": summary_id,
                "content": summary_content,
                "consolidated_count": len(cluster)
            }

        except Exception as e:
            logger.error(f"Error creating summary: {e}")
            return None

    async def _generate_llm_summary(self, cluster: List[Dict[str, Any]]) -> str:
        """Generate summary using LLM"""
        try:
            contents = "\n---\n".join(m["content"] for m in cluster[:10])  # Max 10

            prompt = f"""Consolidate these {len(cluster)} low-importance memories into a concise summary (2-3 sentences):

{contents}

Summary:"""

            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=150
            )

            summary = response["choices"][0]["message"]["content"].strip()
            return summary

        except Exception as e:
            logger.error(f"Error generating LLM summary: {e}")
            # Fallback
            return f"Consolidated {len(cluster)} memories"

    async def _mark_as_consolidated(
        self,
        memory_ids: List[int],
        summary_id: int
    ) -> None:
        """Mark memories as consolidated"""
        try:
            query = text("""
                UPDATE episode
                SET
                    consolidated = TRUE,
                    consolidated_into = :summary_id
                WHERE id = ANY(:memory_ids)
            """)

            self.db.execute(query, {
                "summary_id": summary_id,
                "memory_ids": memory_ids
            })

            logger.debug(f"Marked {len(memory_ids)} memories as consolidated into {summary_id}")

        except Exception as e:
            logger.error(f"Error marking as consolidated: {e}")


def get_consolidation_service(db: Session, llm_client=None) -> MemoryConsolidationService:
    """Get consolidation service instance"""
    return MemoryConsolidationService(db, llm_client)
