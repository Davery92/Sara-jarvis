"""Memory routes — operates on the Episode store (the live memory system).

MemoryTrace is a deprecated legacy model. All chat interactions are stored
as Episode records with pgvector embeddings.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import json
import uuid
import time
import os as _os
import logging

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.episode import Episode
from app.services.embedding_service import embedding_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])

EMBEDDING_DIM = settings.embedding_dim

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore
        url = _os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, decode_responses=True)
        return _redis_client
    except Exception:
        return None


class EpisodeCreate(BaseModel):
    content: str
    role: Optional[str] = None
    source: Optional[str] = "api"
    memory_type: Optional[str] = "manual"
    importance: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None


@router.post("/trace")
async def create_episode(payload: EpisodeCreate, current_user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Create a new episode (memory trace). Generates embedding automatically."""
    try:
        emb = await embedding_service.generate_embedding(payload.content)
    except Exception:
        emb = None

    # Normalize embedding dimension
    if emb:
        if len(emb) < EMBEDDING_DIM:
            emb = emb + [0.0] * (EMBEDDING_DIM - len(emb))
        elif len(emb) > EMBEDDING_DIM:
            emb = emb[:EMBEDDING_DIM]

    try:
        episode_id = str(uuid.uuid4())
        episode = Episode(
            id=episode_id,
            user_id=current_user.id,
            content=payload.content,
            role=payload.role or "user",
            source=payload.source,
            memory_type=payload.memory_type,
            importance=payload.importance or 0.5,
            embedding=emb,
            meta=payload.meta or {},
        )
        db.add(episode)
        db.commit()

        # Push to Redis working set
        try:
            r = _get_redis()
            if r:
                key = f"user:{current_user.id}:memory:recent"
                item = json.dumps({
                    "trace_id": episode_id,  # Keep trace_id key for backwards compat
                    "content": payload.content,
                    "role": payload.role,
                    "ts": int(time.time())
                })
                r.zadd(key, {item: int(time.time())})
                r.zremrangebyrank(key, 0, -1001)
                ttl = int(_os.getenv("REDIS_FOCUS_TTL_SECONDS", "172800"))
                r.expire(key, ttl)
        except Exception:
            pass

        return {"trace_id": episode_id, "episode_id": episode_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to store episode: {e}")


@router.get("/unified-recall")
async def unified_recall(
    q: str = Query(...),
    k: int = Query(10, ge=1, le=50),
    kinds: Optional[str] = Query(None, description="comma-separated: episode,note,document,summary,fact,person,thread"),
    current_user=Depends(get_current_user),
):
    """ONE_MIND §3.4 — the one recall API. Fans out across episodes, notes,
    documents, summaries, facts (PKG), people, and open threads, returning
    traces on one shape with one provenance and one graduated confidence scale
    (observed → inferred → confirmed). This is the recall-paths=1 path callers
    migrate onto so no subsystem keeps a private view of the truth."""
    from app.services.memory_recall import recall as unified
    kind_list = [s.strip() for s in kinds.split(",")] if kinds else None
    return await unified(user_id=str(current_user.id), query=q, k=k, kinds=kind_list)


@router.get("/recall")
async def recall(q: str = Query(...), k: int = Query(10, ge=1, le=100),
                 time_window: Optional[str] = Query(None),
                 current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Semantic recall over episodes using pgvector similarity search."""
    q_emb = await embedding_service.generate_embedding(q)
    if not q_emb:
        raise HTTPException(status_code=502, detail="Embedding service failed")
    if len(q_emb) < EMBEDDING_DIM:
        q_emb = q_emb + [0.0] * (EMBEDDING_DIM - len(q_emb))
    elif len(q_emb) > EMBEDDING_DIM:
        q_emb = q_emb[:EMBEDDING_DIM]

    results: List[Dict[str, Any]] = []
    seen: set = set()

    # 1) Redis recent buffer
    try:
        r = _get_redis()
        if r:
            key = f"user:{current_user.id}:memory:recent"
            raw = r.zrevrange(key, 0, 49)
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
                        "score": 0.0,
                        "source": "redis_recent",
                    })
                    seen.add(tid)
                    if len(results) >= k:
                        return {"query": q, "k": k, "time_window": time_window, "results": results}
                except Exception:
                    continue
    except Exception:
        pass

    # 2) pgvector similarity search on episode table
    try:
        # Check for temporal references in the query (e.g. "what happened Tuesday")
        from app.services.temporal_query_parser import parse_temporal_reference
        temporal_range = parse_temporal_reference(q)

        time_filter = ""
        params: Dict[str, Any] = {
            "user_id": current_user.id,
            "qvec": str(q_emb),
            "k": k,
        }
        if temporal_range:
            # Temporal query detected — use parsed time range instead of default window
            time_filter = " AND e.created_at BETWEEN :t_start AND :t_end"
            params["t_start"] = temporal_range[0]
            params["t_end"] = temporal_range[1]
        elif time_window:
            try:
                days = int(time_window.rstrip('d'))
            except Exception:
                days = 30
            time_filter = f" AND e.created_at >= NOW() - INTERVAL '{days} days'"
        else:
            time_filter = " AND e.created_at >= NOW() - INTERVAL '30 days'"

        sql = f"""
            SELECT e.id, e.content, e.role, e.created_at, e.source, e.importance,
                   (e.embedding <=> CAST(:qvec AS vector)) AS distance,
                   COALESCE(e.access_count, 0) AS access_count,
                   COALESCE(e.rating_boost, 0) AS rating_boost,
                   COALESCE(e.exploration_bonus, 0) AS exploration_bonus
            FROM episode e
            WHERE e.user_id = :user_id
              AND e.embedding IS NOT NULL
              {time_filter}
            ORDER BY (
                0.55 * (1.0 - (e.embedding <=> CAST(:qvec AS vector)))
              + 0.25 * COALESCE(e.importance, 0.5)
              + 0.10 * LEAST(LN(COALESCE(e.access_count, 0) + 1) / 4.6, 1.0)
              + 0.05 * COALESCE(e.rating_boost, 0)
              + 0.05 * COALESCE(e.exploration_bonus, 0)
            ) DESC
            LIMIT :k
        """
        rows = db.execute(sql_text(sql), params).fetchall()
        for row in rows:
            eid = row[0]
            if eid in seen:
                continue
            results.append({
                "trace_id": eid,
                "content": row[1],
                "role": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "source": row[4] or "chat",
                "importance": float(row[5]) if row[5] else None,
                "score": float(row[6]),
            })
            seen.add(eid)
    except Exception as e:
        logger.error(f"Episode recall vector search failed: {e}")

    # Track access counts for recalled episodes (feedback loop)
    if results:
        recalled_ids = [r["trace_id"] for r in results if r.get("trace_id")]
        if recalled_ids:
            try:
                db.execute(sql_text("""
                    UPDATE episode SET access_count = COALESCE(access_count, 0) + 1,
                                       last_accessed = NOW()
                    WHERE id = ANY(:ids) AND user_id = :uid
                """), {"ids": recalled_ids, "uid": str(current_user.id)})
                db.commit()
            except Exception as e:
                logger.debug(f"Access tracking update failed: {e}")

    return {
        "query": q,
        "k": k,
        "time_window": time_window,
        "temporal_detected": temporal_range is not None,
        "results": results,
    }


class ForgetRequest(BaseModel):
    trace_id: str


@router.post("/forget")
async def forget(payload: ForgetRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Delete an episode by ID."""
    try:
        episode = db.query(Episode).filter(
            Episode.id == payload.trace_id,
            Episode.user_id == current_user.id
        ).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")

        db.delete(episode)
        db.commit()

        # Remove from Redis
        try:
            r = _get_redis()
            if r:
                key = f"user:{current_user.id}:memory:recent"
                raw = r.zrange(key, 0, -1)
                for item in raw:
                    try:
                        obj = json.loads(item)
                        if obj.get("trace_id") == payload.trace_id:
                            r.zrem(key, item)
                    except Exception:
                        continue
        except Exception:
            pass

        return {"trace_id": payload.trace_id, "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete episode: {e}")


class UpdateImportanceRequest(BaseModel):
    trace_id: str
    importance: float


@router.put("/importance")
async def update_importance(payload: UpdateImportanceRequest,
                            current_user=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Update an episode's importance score."""
    if not (0.0 <= payload.importance <= 1.0):
        raise HTTPException(status_code=400, detail="Importance must be between 0.0 and 1.0")

    episode = db.query(Episode).filter(
        Episode.id == payload.trace_id,
        Episode.user_id == current_user.id,
    ).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    episode.importance = payload.importance
    db.commit()
    return {"trace_id": payload.trace_id, "importance": payload.importance}



# NOTE: /episodes and /search endpoints live in routes/episodes.py
# (registered without prefix as /memory/episodes and /memory/search)
