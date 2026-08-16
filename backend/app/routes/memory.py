"""Memory routes — operates on the Episode store (the live memory system).

MemoryTrace is a deprecated legacy model. All chat interactions are stored
as Episode records with pgvector embeddings.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
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
        from app.core.redis import get_redis_sync
        _redis_client = get_redis_sync()
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
        # Manual API call, not the hot chat loop — presence-latency
        # ruling 1 (2026-07-31): CPU fallback host.
        emb = await embedding_service.generate_embedding(payload.content, capability="embedding_cognition")
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


@router.get("/verification-question")
async def verification_question(current_user=Depends(get_current_user)):
    """ONE_MIND §3.4 — the ripest unverified fact as one natural yes/no
    question (or null). Marks it asked (anti-nag cooldown + daily cap)."""
    from app.services.fact_verification import pick_question, count_unverified
    q = await pick_question(user_id=str(current_user.id))
    total = await count_unverified()
    return {"question": q, "unverified_remaining": total}


@router.post("/verification-answer")
async def verification_answer(
    payload: Dict[str, Any] = Body(...),
    current_user=Depends(get_current_user),
):
    """Record David's answer: confirmed → the fact graduates to the confirmed
    tier; denied → it is retired."""
    pkg_id = (payload.get("pkg_id") or "").strip()
    if not pkg_id:
        raise HTTPException(status_code=400, detail="pkg_id required")
    confirmed = bool(payload.get("confirmed"))
    from app.services.fact_verification import record_answer
    return await record_answer(str(current_user.id), pkg_id, confirmed)


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
