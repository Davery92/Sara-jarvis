"""
HYDRA Knowledge Retrieval Fusion
Multi-source retrieval with reranking for optimal context
"""
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import json
import logging
import asyncio

logger = logging.getLogger(__name__)


class RetrievalResult(BaseModel):
    """Single retrieval result"""
    source: str  # episodes, notes, documents, health, calendar
    id: str
    content: str
    score: float  # Initial retrieval score
    rerank_score: Optional[float] = None  # After reranking
    metadata: Dict[str, Any] = {}
    timestamp: Optional[datetime] = None


class HydraRetrieval:
    """Multi-source knowledge retrieval with fusion and reranking"""

    def __init__(self, db: Session, redis_client=None, reranker=None, embedding_service=None):
        self.db = db
        self.redis_client = redis_client
        self.reranker = reranker  # Will be set to bge-reranker model
        self.embedding_service = embedding_service  # Optional — used for episode vector search

        # Source weights for fusion scoring
        self.source_weights = {
            "episodes": 1.0,     # Highest priority (conversational memory)
            "notes": 0.9,        # User-created knowledge
            "documents": 0.8,    # Uploaded documents
            "health": 0.7,       # Health data context
            "calendar": 0.6      # Schedule context
        }

        # Cache TTL
        self.cache_ttl = 3600  # 1 hour

    async def retrieve(
        self,
        query: str,
        user_id: str,
        sources: Optional[List[str]] = None,
        top_k: int = 50,
        rerank_top_k: int = 10,
        include_metadata: bool = True
    ) -> List[RetrievalResult]:
        """
        Retrieve and rank knowledge from multiple sources

        Args:
            query: Search query
            user_id: User ID
            sources: List of sources to search (None = all)
            top_k: Initial results per source
            rerank_top_k: Final results after reranking
            include_metadata: Include detailed metadata

        Returns:
            Ranked list of retrieval results
        """
        try:
            # Check cache
            cache_key = f"hydra:{user_id}:{hash(query)}:{','.join(sorted(sources or []))}"

            if self.redis_client:
                cached = await self._get_cached_results(cache_key)
                if cached:
                    logger.debug(f"✅ HYDRA cache hit for query: {query[:50]}")
                    return cached

            # Determine sources
            if sources is None:
                sources = list(self.source_weights.keys())

            # Parallel retrieval from all sources
            logger.info(f"🔍 HYDRA retrieving from {len(sources)} sources: {sources}")

            retrieval_tasks = []

            if "episodes" in sources:
                retrieval_tasks.append(self._retrieve_episodes(query, user_id, top_k))

            if "notes" in sources:
                retrieval_tasks.append(self._retrieve_notes(query, user_id, top_k))

            if "documents" in sources:
                retrieval_tasks.append(self._retrieve_documents(query, user_id, top_k))

            if "health" in sources:
                retrieval_tasks.append(self._retrieve_health_data(query, user_id, top_k))

            if "calendar" in sources:
                retrieval_tasks.append(self._retrieve_calendar(query, user_id, top_k))

            # Execute in parallel
            results_by_source = await asyncio.gather(*retrieval_tasks, return_exceptions=True)

            # Combine results; record each source's contribution to the funnel
            # so we can spot a single-source failure (e.g. Neo4j down) that
            # would otherwise vanish behind return_exceptions=True.
            from app.services import retrieval_observer as _obs
            import time as _time
            all_results = []
            for source_name, source_results in zip(sources, results_by_source):
                if isinstance(source_results, Exception):
                    logger.error(f"Source {source_name} retrieval failed: {source_results}")
                    _obs.record(
                        f"hydra.{source_name}", query, 0, 0.0,
                        error=type(source_results).__name__,
                    )
                    continue
                _obs.record(f"hydra.{source_name}", query, len(source_results), 0.0)
                all_results.extend(source_results)

            logger.info(f"Retrieved {len(all_results)} total results before fusion")

            # Apply fusion scoring
            fusion_results = await self._apply_fusion_scoring(all_results, query)

            # Rerank top results
            if self.reranker and len(fusion_results) > 0:
                reranked = await self._rerank_results(query, fusion_results[:50], rerank_top_k)
            else:
                # No reranker, just take top by fusion score
                reranked = sorted(fusion_results, key=lambda r: r.score, reverse=True)[:rerank_top_k]

            # Cache results
            if self.redis_client:
                await self._cache_results(cache_key, reranked)

            logger.info(f"✅ HYDRA returning {len(reranked)} results")
            return reranked

        except Exception as e:
            logger.error(f"HYDRA retrieval error: {e}", exc_info=True)
            return []

    async def _retrieve_episodes(
        self,
        query: str,
        user_id: str,
        limit: int
    ) -> List[RetrievalResult]:
        """Retrieve from episodic memory via pgvector similarity + composite scoring.

        Falls back to recency ordering only if no embedding service is available
        or embedding generation fails — degraded retrieval is logged so callers
        can tell when semantic search is offline.
        """
        try:
            embedding_service = self.embedding_service
            if embedding_service is None:
                try:
                    from app.services.embedding_service import EmbeddingService
                    embedding_service = EmbeddingService()
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"HYDRA: embedding service unavailable ({exc}); episodes degraded to recency")

            q_emb = None
            if embedding_service is not None:
                try:
                    q_emb = await embedding_service.generate_embedding(query)
                except Exception as exc:
                    logger.warning(f"HYDRA: query embedding failed ({exc}); episodes degraded to recency")

            if q_emb:
                sql = text("""
                    SELECT
                        e.id,
                        e.content,
                        e.importance,
                        e.created_at,
                        e.emotional_tone,
                        e.topics,
                        1 - (e.embedding <=> CAST(:qvec AS vector)) AS similarity,
                        (
                            (1 - (e.embedding <=> CAST(:qvec AS vector))) * 0.55 +
                            COALESCE(e.importance, 0.5) * 0.25 +
                            LEAST(LN(COALESCE(e.access_count, 0) + 1) / 4.6, 1.0) * 0.10 +
                            COALESCE(e.rating_boost, 0.0) * 0.05 +
                            COALESCE(e.exploration_bonus, 0.0) * 0.05
                        ) AS composite_score
                    FROM episode e
                    WHERE e.user_id = :user_id
                      AND e.embedding IS NOT NULL
                    ORDER BY composite_score DESC
                    LIMIT :limit
                """)
                result = self.db.execute(sql, {
                    "user_id": user_id,
                    "qvec": str(q_emb),
                    "limit": limit,
                })
                rows = result.fetchall()
                return [
                    RetrievalResult(
                        source="episodes",
                        id=str(row.id),
                        content=row.content,
                        score=float(row.composite_score),
                        metadata={
                            "importance": row.importance,
                            "similarity": float(row.similarity),
                            "created_at": row.created_at.isoformat() if row.created_at else None,
                            "emotional_tone": row.emotional_tone,
                            "topics": row.topics,
                        },
                        timestamp=row.created_at,
                    )
                    for row in rows
                ]

            # Degraded fallback — recency only
            sql = text("""
                SELECT id, content, importance, created_at, emotional_tone, topics
                FROM episode
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = self.db.execute(sql, {"user_id": user_id, "limit": limit})
            return [
                RetrievalResult(
                    source="episodes",
                    id=str(row.id),
                    content=row.content,
                    score=0.5,
                    metadata={
                        "importance": row.importance,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "emotional_tone": row.emotional_tone,
                        "topics": row.topics,
                        "degraded": True,
                    },
                    timestamp=row.created_at,
                )
                for row in result.fetchall()
            ]

        except Exception as e:
            logger.error(f"Episode retrieval error: {e}")
            return []

    async def _retrieve_notes(
        self,
        query: str,
        user_id: str,
        limit: int
    ) -> List[RetrievalResult]:
        """Retrieve from notes"""
        try:
            # Full-text search on notes
            sql = text("""
                SELECT
                    id,
                    title,
                    content,
                    created_at,
                    updated_at,
                    ts_rank(to_tsvector('english', title || ' ' || content), plainto_tsquery('english', :query)) as rank
                FROM notes
                WHERE user_id = :user_id
                AND (
                    to_tsvector('english', title || ' ' || content) @@ plainto_tsquery('english', :query)
                    OR title ILIKE :query_like
                    OR content ILIKE :query_like
                )
                ORDER BY rank DESC, updated_at DESC
                LIMIT :limit
            """)

            result = self.db.execute(sql, {
                "user_id": user_id,
                "query": query,
                "query_like": f"%{query}%",
                "limit": limit
            })

            results = []
            for row in result.fetchall():
                content_preview = f"{row.title}\n\n{row.content[:500]}"

                results.append(RetrievalResult(
                    source="notes",
                    id=str(row.id),
                    content=content_preview,
                    score=row.rank if row.rank else 0.5,
                    metadata={
                        "title": row.title,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None
                    },
                    timestamp=row.updated_at or row.created_at
                ))

            return results

        except Exception as e:
            logger.error(f"Notes retrieval error: {e}")
            return []

    async def _retrieve_documents(
        self,
        query: str,
        user_id: str,
        limit: int
    ) -> List[RetrievalResult]:
        """Retrieve from documents"""
        try:
            sql = text("""
                SELECT
                    id,
                    filename,
                    content_text,
                    created_at,
                    file_type,
                    ts_rank(to_tsvector('english', content_text), plainto_tsquery('english', :query)) as rank
                FROM documents
                WHERE user_id = :user_id
                AND content_text IS NOT NULL
                AND to_tsvector('english', content_text) @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """)

            result = self.db.execute(sql, {
                "user_id": user_id,
                "query": query,
                "limit": limit
            })

            results = []
            for row in result.fetchall():
                results.append(RetrievalResult(
                    source="documents",
                    id=str(row.id),
                    content=row.content_text[:500] if row.content_text else "",
                    score=row.rank if row.rank else 0.5,
                    metadata={
                        "filename": row.filename,
                        "file_type": row.file_type,
                        "created_at": row.created_at.isoformat() if row.created_at else None
                    },
                    timestamp=row.created_at
                ))

            return results

        except Exception as e:
            logger.error(f"Document retrieval error: {e}")
            return []

    async def _retrieve_health_data(
        self,
        query: str,
        user_id: str,
        limit: int
    ) -> List[RetrievalResult]:
        """Retrieve health data context"""
        try:
            # Look for health-related keywords
            health_keywords = ["sleep", "workout", "exercise", "fitness", "recovery", "hrv", "heart", "weight"]

            if not any(kw in query.lower() for kw in health_keywords):
                return []  # Not health-related query

            # Get recent recovery logs
            sql = text("""
                SELECT
                    id,
                    sleep_hours,
                    hrv,
                    heart_rate,
                    soreness_level,
                    body_weight,
                    notes,
                    logged_at
                FROM recovery_log
                WHERE user_id = :user_id
                ORDER BY logged_at DESC
                LIMIT :limit
            """)

            result = self.db.execute(sql, {
                "user_id": user_id,
                "limit": min(limit, 7)  # Max 7 days
            })

            results = []
            for row in result.fetchall():
                content = f"Recovery data from {row.logged_at.date()}: {row.sleep_hours}h sleep, HRV {row.hrv}, HR {row.heart_rate}, soreness {row.soreness_level}/10"
                if row.notes:
                    content += f". Notes: {row.notes}"

                results.append(RetrievalResult(
                    source="health",
                    id=str(row.id),
                    content=content,
                    score=0.7,  # Fixed score for health data
                    metadata={
                        "sleep_hours": row.sleep_hours,
                        "hrv": row.hrv,
                        "logged_at": row.logged_at.isoformat() if row.logged_at else None
                    },
                    timestamp=row.logged_at
                ))

            return results

        except Exception as e:
            logger.error(f"Health data retrieval error: {e}")
            return []

    async def _retrieve_calendar(
        self,
        query: str,
        user_id: str,
        limit: int
    ) -> List[RetrievalResult]:
        """Retrieve calendar context"""
        try:
            # Look for time-related keywords
            time_keywords = ["today", "tomorrow", "schedule", "meeting", "appointment", "event", "calendar", "when"]

            if not any(kw in query.lower() for kw in time_keywords):
                return []  # Not schedule-related

            # Get upcoming and recent events
            sql = text("""
                SELECT
                    id,
                    title,
                    description,
                    starts_at,
                    ends_at,
                    location
                FROM calendar_events
                WHERE user_id = :user_id
                AND starts_at BETWEEN :start_range AND :end_range
                ORDER BY starts_at
                LIMIT :limit
            """)

            now = datetime.now(timezone.utc)
            start_range = now - timedelta(days=1)
            end_range = now + timedelta(days=7)

            result = self.db.execute(sql, {
                "user_id": user_id,
                "start_range": start_range,
                "end_range": end_range,
                "limit": limit
            })

            results = []
            for row in result.fetchall():
                content = f"Event: {row.title} on {row.starts_at.date()} at {row.starts_at.time()}"
                if row.description:
                    content += f". {row.description}"
                if row.location:
                    content += f" at {row.location}"

                results.append(RetrievalResult(
                    source="calendar",
                    id=str(row.id),
                    content=content,
                    score=0.6,  # Fixed score for calendar
                    metadata={
                        "title": row.title,
                        "starts_at": row.starts_at.isoformat() if row.starts_at else None,
                        "location": row.location
                    },
                    timestamp=row.starts_at
                ))

            return results

        except Exception as e:
            logger.error(f"Calendar retrieval error: {e}")
            return []

    async def _apply_fusion_scoring(
        self,
        results: List[RetrievalResult],
        query: str
    ) -> List[RetrievalResult]:
        """Apply fusion scoring combining source weights, recency, and importance"""
        scored_results = []

        for result in results:
            # Base score from retrieval
            base_score = result.score

            # Source weight
            source_weight = self.source_weights.get(result.source, 0.5)

            # Recency boost (newer = higher)
            recency_boost = 1.0
            if result.timestamp:
                # Normalize both sides to tz-aware UTC to avoid naive/aware mix
                ts = result.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                days_ago = (datetime.now(timezone.utc) - ts).days
                recency_boost = max(0.5, 1.0 - (days_ago / 365))  # Decay over a year

            # Importance boost (for episodes)
            importance_boost = 1.0
            if result.source == "episodes" and "importance" in result.metadata:
                importance_boost = 0.8 + (result.metadata["importance"] * 0.4)  # 0.8 to 1.2 range

            # Combined fusion score
            fusion_score = base_score * source_weight * recency_boost * importance_boost

            # Update result
            result.score = fusion_score
            scored_results.append(result)

        # Sort by fusion score
        scored_results.sort(key=lambda r: r.score, reverse=True)

        return scored_results

    async def _rerank_results(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int
    ) -> List[RetrievalResult]:
        """Rerank results using reranker model"""
        if not self.reranker:
            logger.warning("No reranker available, skipping reranking")
            return results[:top_k]

        try:
            # Prepare pairs for reranking
            pairs = [(query, result.content) for result in results]

            # Get reranking scores
            rerank_scores = await self.reranker.predict(pairs)

            # Update scores
            for result, rerank_score in zip(results, rerank_scores):
                result.rerank_score = rerank_score

            # Sort by rerank score
            reranked = sorted(results, key=lambda r: r.rerank_score or 0, reverse=True)

            logger.info(f"Reranked {len(results)} results")

            return reranked[:top_k]

        except Exception as e:
            logger.error(f"Reranking error: {e}")
            return results[:top_k]

    async def _get_cached_results(self, cache_key: str) -> Optional[List[RetrievalResult]]:
        """Get cached results from Redis"""
        try:
            cached = await self.redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return [RetrievalResult(**r) for r in data]
        except Exception as e:
            logger.warning(f"Cache retrieval failed: {e}")

        return None

    async def _cache_results(self, cache_key: str, results: List[RetrievalResult]):
        """Cache results in Redis"""
        try:
            data = [r.dict() for r in results]
            await self.redis_client.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(data, default=str)
            )
        except Exception as e:
            logger.warning(f"Cache storage failed: {e}")


def get_hydra_retrieval(
    db: Session,
    redis_client=None,
    reranker=None,
    embedding_service=None,
) -> HydraRetrieval:
    """Get HYDRA retrieval instance"""
    return HydraRetrieval(db, redis_client, reranker, embedding_service)
