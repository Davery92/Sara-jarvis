"""
Human-Like Memory Service

This service implements a three-tiered memory retrieval system:
1. Redis working set (hot/recent memories)
2. Postgres with pgvector HNSW (vector similarity search)
3. Neo4j graph edges (conceptual connections)

Architecture:
- Write traces to Postgres (memory_trace + memory_embedding per head)
- Cache recent traces in Redis sorted set for fast recency access
- Read via Redis → Postgres HNSW → graph edges expansion
- Consolidate via nightly dreams (summarization + edge extraction)
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import json
import uuid
import time
import logging
import os

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Production memory service implementing the full retrieval pipeline.
    """

    def __init__(self, redis_client=None, db_session_factory=None):
        """
        Initialize memory service with Redis and database connections.

        Args:
            redis_client: Redis client for working set cache, OR a db session directly
            db_session_factory: SQLAlchemy SessionLocal factory
        """
        # Support passing a db session directly (for tool compatibility)
        if redis_client is not None and hasattr(redis_client, 'query'):
            # It's a SQLAlchemy session, not a redis client
            self.db = redis_client
            self.redis = None
            self.SessionLocal = None
        else:
            self.redis = redis_client
            self.SessionLocal = db_session_factory
            self.db = None
        self._embedding_service = None
        self._redis_focus_ttl = int(os.getenv("REDIS_FOCUS_TTL_SECONDS", "172800"))  # 48 hours
        self._redis_max_recent = 1000

    def _get_redis(self):
        """Get or initialize Redis client"""
        if self.redis:
            return self.redis

        # Lazy initialization
        try:
            import redis
            url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            self.redis = redis.from_url(url, decode_responses=True)
            logger.info("✅ Redis client initialized for memory service")
            return self.redis
        except Exception as e:
            logger.warning(f"⚠️ Redis not available for memory service: {e}")
            return None

    def _get_embedding_service(self):
        """Get or initialize embedding service"""
        if self._embedding_service:
            return self._embedding_service

        try:
            from app.services.embeddings import get_embedding
            self._embedding_service = get_embedding
            return self._embedding_service
        except Exception as e:
            logger.error(f"Failed to initialize embedding service: {e}")
            return None

    async def store_trace(
        self,
        user_id: str,
        content: str,
        role: str = "assistant",
        heads: Optional[List[str]] = None,
        salience: Optional[float] = None,
        source: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Store a memory trace with embeddings and cache in Redis working set.

        Args:
            user_id: User identifier
            content: Memory content text
            role: Role (user, assistant, system, summary)
            heads: List of embedding heads to generate (e.g., ['semantic', 'entity'])
            salience: Importance score (0-1), auto-calculated if None
            source: Source metadata dict
            meta: Additional metadata dict

        Returns:
            trace_id: UUID of created trace

        Raises:
            Exception: If storage fails
        """
        from app.main_simple import (
            MemoryTrace, MemoryEmbedding,
            EMBEDDING_DIM, PGVECTOR_AVAILABLE, DATABASE_URL
        )

        heads = heads or ["semantic"]
        embedding_fn = self._get_embedding_service()

        # Generate embeddings per head (best-effort)
        q_embeddings: Dict[str, List[float]] = {}
        if embedding_fn:
            for h in heads:
                try:
                    emb = await embedding_fn(content)
                    if emb:
                        # Normalize to EMBEDDING_DIM with logging
                        original_dim = len(emb)
                        if original_dim != EMBEDDING_DIM:
                            logger.warning(
                                f"Embedding dimension mismatch for head '{h}': got {original_dim}, expected {EMBEDDING_DIM}. "
                                f"{'Padding' if original_dim < EMBEDDING_DIM else 'Truncating'} embedding."
                            )
                            if original_dim < EMBEDDING_DIM:
                                emb = emb + [0.0] * (EMBEDDING_DIM - original_dim)
                            else:
                                emb = emb[:EMBEDDING_DIM]
                        q_embeddings[h] = emb
                    else:
                        logger.warning(f"Embedding service returned empty result for head '{h}' - skipping storage")
                except Exception as e:
                    logger.error(f"Failed to generate embedding for head '{h}': {e}", exc_info=True)

        # Store in database
        db: Session = self.SessionLocal()
        try:
            trace_id = str(uuid.uuid4())
            trace = MemoryTrace(
                id=trace_id,
                user_id=user_id,
                content=content,
                role=role,
                salience=salience or self._auto_calculate_salience(content, role),
                source=json.dumps(source) if source else None,
                meta=json.dumps(meta) if meta else None,
            )
            db.add(trace)

            # Store embeddings
            for head, emb in q_embeddings.items():
                me = MemoryEmbedding(
                    trace_id=trace_id,
                    head=head,
                    embedding=emb if (PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql")) else json.dumps(emb),
                )
                db.add(me)

            db.commit()
            logger.info(f"✅ Stored memory trace {trace_id} with {len(q_embeddings)} embeddings")

            # Push to Redis working set (recency buffer)
            try:
                r = self._get_redis()
                if r:
                    key = f"user:{user_id}:memory:recent"
                    item = json.dumps({
                        "trace_id": trace_id,
                        "content": content,
                        "role": role,
                        "ts": int(time.time())
                    })
                    r.zadd(key, {item: int(time.time())})
                    # Keep only latest N items
                    r.zremrangebyrank(key, 0, -(self._redis_max_recent + 1))
                    r.expire(key, self._redis_focus_ttl)
                    logger.debug(f"📌 Cached trace {trace_id} in Redis working set")
            except Exception as e:
                logger.warning(f"Failed to cache trace in Redis: {e}")

            return trace_id

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to store memory trace: {e}")
            raise
        finally:
            db.close()

    async def recall(
        self,
        user_id: str,
        q: str,
        k: int = 10,
        heads: Optional[List[str]] = None,
        time_window: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Recall top-k traces using three-tiered retrieval:
        1. Redis working set (recent memories)
        2. Postgres HNSW vector similarity
        3. Graph edge expansion

        Args:
            user_id: User identifier
            q: Query string
            k: Number of results to return
            heads: Filter by embedding heads
            time_window: Time window like "7d", "30d" (default: 30d)

        Returns:
            List of trace dicts with scores, sorted by relevance
        """
        from app.main_simple import (
            MemoryTrace, MemoryEmbedding, MemoryEdge,
            EMBEDDING_DIM, PGVECTOR_AVAILABLE, DATABASE_URL
        )

        # Generate query embedding
        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            logger.error("Embedding service not available for recall")
            return []

        try:
            q_emb = await embedding_fn(q)
            if not q_emb:
                logger.error("Failed to generate query embedding - embedding service returned empty result")
                return []

            # Normalize embedding dimension with logging
            original_dim = len(q_emb)
            if original_dim != EMBEDDING_DIM:
                logger.warning(
                    f"Query embedding dimension mismatch: got {original_dim}, expected {EMBEDDING_DIM}. "
                    f"{'Padding' if original_dim < EMBEDDING_DIM else 'Truncating'} for search."
                )
                if original_dim < EMBEDDING_DIM:
                    q_emb = q_emb + [0.0] * (EMBEDDING_DIM - original_dim)
                else:
                    q_emb = q_emb[:EMBEDDING_DIM]
        except Exception as e:
            logger.error(f"Failed to generate embedding for query: {e}", exc_info=True)
            return []

        db: Session = self.SessionLocal()
        try:
            results: List[Dict[str, Any]] = []
            seen: set[str] = set()

            # 1) Check Redis recent traces first
            try:
                r = self._get_redis()
                if r:
                    key = f"user:{user_id}:memory:recent"
                    raw = r.zrevrange(key, 0, 49)  # Latest 50
                    for item in raw:
                        try:
                            obj = json.loads(item)
                            tid = obj.get("trace_id")
                            if not tid or tid in seen:
                                continue
                            results.append({
                                "trace_id": tid,
                                "content": obj.get("content"),
                                "role": obj.get("role"),
                                "created_at": None,
                                "head": "recent",
                                "score": 0.0  # Perfect recency score
                            })
                            seen.add(tid)
                            if len(results) >= k:
                                logger.info(f"🔍 Recall satisfied from Redis cache: {len(results)} results")
                                return results
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Redis recall failed, falling back to database: {e}")

            # 2) Postgres HNSW vector similarity search
            if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql"):
                head_filter = ""
                params: Dict[str, Any] = {
                    "user_id": user_id,
                    "qvec": str(q_emb),
                    "k": k,
                }

                # Time window filter
                time_filter = ""
                if time_window:
                    try:
                        days = int(time_window.rstrip('d'))
                    except Exception:
                        days = 30
                    time_filter = f" AND t.created_at >= NOW() - INTERVAL '{days} days'"
                else:
                    # Default 30-day hot tier window
                    time_filter = " AND t.created_at >= NOW() - INTERVAL '30 days'"

                # Head filter
                if heads:
                    head_filter = " AND e.head = ANY(:heads)"
                    params["heads"] = heads

                sql = f"""
                    SELECT t.id, t.content, t.role, t.created_at, e.head,
                           (e.embedding <=> CAST(:qvec AS vector)) AS distance,
                           COALESCE(t.salience, 0.5) AS salience
                    FROM memory_embedding e
                    JOIN memory_trace t ON t.id = e.trace_id
                    WHERE t.user_id = :user_id
                    {head_filter}
                    {time_filter}
                    ORDER BY (
                        0.65 * (1.0 - (e.embedding <=> CAST(:qvec AS vector)))
                      + 0.35 * COALESCE(t.salience, 0.5)
                    ) DESC
                    LIMIT :k
                """

                rows = db.execute(sql_text(sql), params).fetchall()
                for row in rows:
                    tid = row[0]
                    if tid not in seen:
                        results.append({
                            "trace_id": tid,
                            "content": row[1],
                            "role": row[2],
                            "created_at": row[3].isoformat() if row[3] else None,
                            "head": row[4],
                            "score": float(row[5]),
                        })
                        seen.add(tid)

                logger.info(f"🔍 Vector search returned {len(results)} results")

                # 3) Expand via graph edges (1-hop neighbors of top results)
                if results and len(results) < k:
                    top_ids = [r["trace_id"] for r in results[:min(5, len(results))]]
                    edge_sql = sql_text("""
                        SELECT t.id, t.content, t.role, t.created_at, 'edge' AS head
                        FROM memory_edge me
                        JOIN memory_trace t ON t.id = me.dst
                        WHERE me.src = ANY(:ids) AND t.user_id = :user_id
                        LIMIT :cap
                    """)
                    edge_rows = db.execute(edge_sql, {
                        "ids": top_ids,
                        "user_id": user_id,
                        "cap": k - len(results)
                    }).fetchall()

                    for row in edge_rows:
                        tid = row[0]
                        if tid not in seen:
                            results.append({
                                "trace_id": tid,
                                "content": row[1],
                                "role": row[2],
                                "created_at": row[3].isoformat() if row[3] else None,
                                "head": row[4],
                                "score": 0.5  # Moderate score for graph-connected memories
                            })
                            seen.add(tid)

                    logger.info(f"🕸️ Graph expansion added {len(edge_rows)} related memories")

            else:
                # Fallback: naive cosine similarity in Python
                logger.warning("Using fallback in-memory similarity search")
                import numpy as np

                qv = np.array(q_emb, dtype=float)
                query = db.query(MemoryEmbedding, MemoryTrace).join(
                    MemoryTrace, MemoryTrace.id == MemoryEmbedding.trace_id
                )
                query = query.filter(MemoryTrace.user_id == user_id)
                if heads:
                    query = query.filter(MemoryEmbedding.head.in_(heads))

                items = query.order_by(MemoryEmbedding.created_at.desc()).limit(500).all()
                scored = []

                for me, mt in items:
                    try:
                        ev = json.loads(me.embedding) if isinstance(me.embedding, str) else me.embedding
                        v = np.array(ev, dtype=float)
                        sim = float(np.dot(qv, v) / (np.linalg.norm(qv) * np.linalg.norm(v) + 1e-8))
                        scored.append((sim, mt, me.head))
                    except Exception:
                        continue

                scored.sort(key=lambda x: x[0], reverse=True)
                for sim, mt, head in scored[:k]:
                    if mt.id not in seen:
                        results.append({
                            "trace_id": mt.id,
                            "content": mt.content,
                            "role": mt.role,
                            "created_at": mt.created_at.isoformat() if mt.created_at else None,
                            "head": head,
                            "score": float(1.0 - sim),  # Distance-like score
                        })
                        seen.add(mt.id)

            logger.info(f"🧠 Recall complete: {len(results)} total results")
            return results[:k]  # Ensure we don't exceed k

        except Exception as e:
            logger.error(f"Memory recall failed: {e}")
            return []
        finally:
            db.close()

    # consolidate_day() removed — legacy MemoryTrace-based consolidation
    # superseded by NightlyDreamService (Episode-based, runs at 2 AM)

    async def forget(self, user_id: str, trace_id: str) -> bool:
        """
        Hard delete a memory trace with cascading cleanup:
        1. Remove from Redis working set
        2. Delete embeddings
        3. Delete graph edges
        4. Delete trace

        Args:
            user_id: User identifier (for authorization)
            trace_id: Trace to delete

        Returns:
            True if deleted successfully

        Raises:
            ValueError: If trace not found or doesn't belong to user
        """
        from app.main_simple import MemoryTrace, MemoryEmbedding, MemoryEdge

        db: Session = self.SessionLocal()
        try:
            # Verify trace belongs to user
            trace = db.query(MemoryTrace).filter(
                MemoryTrace.id == trace_id,
                MemoryTrace.user_id == user_id
            ).first()

            if not trace:
                raise ValueError(f"Trace {trace_id} not found or access denied")

            # Delete embeddings
            db.query(MemoryEmbedding).filter(MemoryEmbedding.trace_id == trace_id).delete()

            # Delete graph edges (both incoming and outgoing)
            db.query(MemoryEdge).filter(
                (MemoryEdge.src == trace_id) | (MemoryEdge.dst == trace_id)
            ).delete(synchronize_session=False)

            # Delete trace
            db.delete(trace)
            db.commit()

            # Remove from Redis working set
            try:
                r = self._get_redis()
                if r:
                    key = f"user:{user_id}:memory:recent"
                    raw = r.zrange(key, 0, -1)
                    for item in raw:
                        try:
                            obj = json.loads(item)
                            if obj.get("trace_id") == trace_id:
                                r.zrem(key, item)
                                break
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Failed to remove trace from Redis: {e}")

            logger.info(f"🗑️ Deleted memory trace {trace_id}")
            return True

        except ValueError:
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete trace: {e}")
            raise
        finally:
            db.close()

    async def search_memory(
        self,
        user_id: str,
        query: str,
        scopes: List[str] = None,
        limit: int = 6
    ) -> List[Dict[str, Any]]:
        """
        Search memory across episodes, notes, documents using semantic similarity.

        Args:
            user_id: User identifier
            query: Search query
            scopes: List of scopes to search (episodes, notes, docs, summaries)
            limit: Maximum results per scope

        Returns:
            List of search results with type, text, score, etc.
        """
        from app.services import retrieval_observer
        import time as _time
        _funnel_start = _time.monotonic()

        if scopes is None:
            scopes = ["episodes", "notes", "docs", "summaries"]

        results: List[Dict[str, Any]] = []

        # Get embedding for query
        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            logger.error("Embedding service not available")
            retrieval_observer.record(
                "memory_service.search_memory", query, 0,
                (_time.monotonic() - _funnel_start) * 1000.0,
                degraded=True, error="embedding_service_unavailable",
                metadata={"scopes": scopes},
            )
            return results

        query_embedding = await embedding_fn(query)
        if not query_embedding:
            logger.error("Failed to generate query embedding")
            retrieval_observer.record(
                "memory_service.search_memory", query, 0,
                (_time.monotonic() - _funnel_start) * 1000.0,
                degraded=True, error="query_embedding_failed",
                metadata={"scopes": scopes},
            )
            return results

        # Get db session - support both init patterns. NOTE: __init__ always
        # sets self.db (to None on the factory path), so the old
        # `hasattr(self, 'db')` guard was always True and crashed with
        # `NoneType has no attribute 'execute'` whenever the service was
        # created with a db_session_factory. Check for a real session instead.
        if getattr(self, 'db', None) is not None:
            db = self.db
            should_close = False
        elif self.SessionLocal:
            db = self.SessionLocal()
            should_close = True
        else:
            logger.error("No database session available")
            return results

        try:
            # Search episodes if in scope
            if "episodes" in scopes:
                from app.main_simple import Episode, PGVECTOR_AVAILABLE, DATABASE_URL

                if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql"):
                    # Parameterized pgvector similarity with composite scoring.
                    # Mirrors main_simple.py retrieve_episodes_with_window so memory
                    # search and context retrieval rank consistently.
                    episode_results = db.execute(sql_text("""
                        SELECT
                            e.id, e.content, e.role, e.source, e.created_at,
                            1 - (e.embedding <=> CAST(:qvec AS vector)) as similarity,
                            (
                                (1 - (e.embedding <=> CAST(:qvec AS vector))) * 0.55 +
                                COALESCE(e.importance, 0.5) * 0.25 +
                                LEAST(LN(COALESCE(e.access_count, 0) + 1) / 4.6, 1.0) * 0.10 +
                                COALESCE(e.rating_boost, 0.0) * 0.05 +
                                COALESCE(e.exploration_bonus, 0.0) * 0.05
                            ) as composite_score,
                            COALESCE(e.importance, 0.5) as importance
                        FROM episode e
                        WHERE e.user_id = :user_id
                          AND e.embedding IS NOT NULL
                        ORDER BY composite_score DESC
                        LIMIT :limit
                    """), {
                        "user_id": user_id,
                        "qvec": str(query_embedding),
                        "limit": limit,
                    }).fetchall()

                    for row in episode_results:
                        results.append({
                            "type": "episode",
                            "episode_id": row[0],
                            "text": row[1],
                            "role": row[2],
                            "source": row[3] or "chat",
                            "created_at": row[4].isoformat() if row[4] else "",
                            "similarity": float(row[5]),
                            "score": float(row[6]),
                            # Arc 5.2: exposed so callers (memory_recall) can
                            # derive a real graduated confidence tier instead
                            # of a hardcoded per-kind label.
                            "importance": float(row[7]),
                        })

            # Search notes if in scope
            if "notes" in scopes:
                from app.main_simple import Note

                # For now, basic text search on notes
                notes = db.query(Note).filter(
                    Note.user_id == user_id
                ).order_by(Note.updated_at.desc()).limit(limit).all()

                for note in notes:
                    # Simple relevance scoring based on query terms
                    score = 0.5
                    query_lower = query.lower()
                    if query_lower in note.title.lower():
                        score = 0.8
                    elif query_lower in note.content.lower():
                        score = 0.7

                    results.append({
                        "type": "note",
                        "note_id": note.id,
                        "title": note.title,
                        "text": note.content[:500],
                        "created_at": note.created_at.isoformat() if note.created_at else "",
                        "score": score
                    })

            # Sort all results by score
            results.sort(key=lambda x: x.get("score", 0), reverse=True)

            top = results[:limit * 2]
            retrieval_observer.record(
                "memory_service.search_memory", query, len(top),
                (_time.monotonic() - _funnel_start) * 1000.0,
                metadata={"scopes": scopes, "raw_count": len(results)},
            )
            return top  # Return top results across all scopes

        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            retrieval_observer.record(
                "memory_service.search_memory", query, 0,
                (_time.monotonic() - _funnel_start) * 1000.0,
                error=type(e).__name__,
                metadata={"scopes": scopes},
            )
            raise
        finally:
            if should_close:
                db.close()

    def _auto_calculate_salience(self, content: str, role: str) -> float:
        """
        Auto-calculate salience (importance) score for content.

        Simple heuristic for now:
        - User input: 0.6
        - Assistant responses: 0.5
        - System/summary: 0.4
        - Length bonus: +0.1 if > 200 chars
        - Keyword bonus: +0.1 for important keywords

        TODO Phase 2: Use LLM to calculate semantic importance
        """
        base_salience = {
            "user": 0.6,
            "assistant": 0.5,
            "system": 0.4,
            "summary": 0.4
        }.get(role, 0.5)

        # Length bonus
        if len(content) > 200:
            base_salience += 0.1

        # Keyword bonus
        important_keywords = ["important", "urgent", "remember", "todo", "deadline", "note"]
        content_lower = content.lower()
        if any(kw in content_lower for kw in important_keywords):
            base_salience += 0.1

        return min(base_salience, 1.0)


# Global service instance (lazy initialization)
_memory_service_instance = None


def get_memory_service(redis_client=None, db_session_factory=None) -> MemoryService:
    """Get or create global MemoryService instance"""
    global _memory_service_instance

    if _memory_service_instance is None:
        _memory_service_instance = MemoryService(redis_client, db_session_factory)
        logger.info("✅ MemoryService initialized")

    return _memory_service_instance
