from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import json
import uuid
import time
import os as _os

from app.main_simple import (
    SessionLocal,
    get_current_user,
    embedding_service,
    EMBEDDING_DIM,
    PGVECTOR_AVAILABLE,
    DATABASE_URL,
    MemoryTrace,
    MemoryEmbedding,
)


router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryTraceCreate(BaseModel):
    content: str
    role: Optional[str] = None
    heads: Optional[List[str]] = None  # e.g., ["semantic", "entity"]
    salience: Optional[float] = None
    source: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None

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


@router.post("/trace")
async def create_trace(payload: MemoryTraceCreate, current_user=Depends(get_current_user)):
    heads = payload.heads or ["semantic"]
    # Generate embeddings per head (same content for now; future: head-specific transforms)
    q_embeddings: Dict[str, List[float]] = {}
    for h in heads:
        emb = await embedding_service.generate_embedding(payload.content)
        if not emb:
            raise HTTPException(status_code=502, detail="Embedding service failed")
        # Normalize to EMBEDDING_DIM
        if len(emb) < EMBEDDING_DIM:
            emb = emb + [0.0] * (EMBEDDING_DIM - len(emb))
        elif len(emb) > EMBEDDING_DIM:
            emb = emb[:EMBEDDING_DIM]
        q_embeddings[h] = emb

    db: Session = SessionLocal()
    try:
        trace_id = str(uuid.uuid4())
        trace = MemoryTrace(
            id=trace_id,
            user_id=current_user.id,
            content=payload.content,
            role=payload.role,
            salience=payload.salience,
            source=json.dumps(payload.source) if payload.source else None,
            meta=json.dumps(payload.meta) if payload.meta else None,
        )
        db.add(trace)

        for head, emb in q_embeddings.items():
            me = MemoryEmbedding(
                trace_id=trace_id,
                head=head,
                embedding=emb if (PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql")) else json.dumps(emb),
            )
            db.add(me)

        db.commit()
        # Push to Redis working set (recency buffer)
        try:
            r = _get_redis()
            if r:
                key = f"user:{current_user.id}:memory:recent"
                item = json.dumps({
                    "trace_id": trace_id,
                    "content": payload.content,
                    "role": payload.role,
                    "ts": int(time.time())
                })
                r.zadd(key, {item: int(time.time())})
                # keep only latest 1000
                r.zremrangebyrank(key, 0, -1001)
                ttl = int(_os.getenv("REDIS_FOCUS_TTL_SECONDS", "172800"))
                r.expire(key, ttl)
        except Exception:
            pass

        return {"trace_id": trace_id, "heads": list(q_embeddings.keys())}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to store trace: {e}")
    finally:
        db.close()


@router.get("/recall")
async def recall(q: str = Query(...), k: int = Query(10, ge=1, le=100),
                 heads: Optional[str] = Query(None), time_window: Optional[str] = Query(None),
                 current_user=Depends(get_current_user)):
    heads_list: Optional[List[str]] = [h.strip() for h in heads.split(",")] if heads else None
    # Compute query embedding
    q_emb = await embedding_service.generate_embedding(q)
    if not q_emb:
        raise HTTPException(status_code=502, detail="Embedding service failed")
    if len(q_emb) < EMBEDDING_DIM:
        q_emb = q_emb + [0.0] * (EMBEDDING_DIM - len(q_emb))
    elif len(q_emb) > EMBEDDING_DIM:
        q_emb = q_emb[:EMBEDDING_DIM]

    db: Session = SessionLocal()
    try:
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # 1) Redis recent
        try:
            r = _get_redis()
            if r:
                key = f"user:{current_user.id}:memory:recent"
                raw = r.zrevrange(key, 0, 49)  # latest 50
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
                            "score": 0.0
                        })
                        seen.add(tid)
                        if len(results) >= k:
                            return {
                                "query": q,
                                "k": k,
                                "heads": heads_list,
                                "time_window": time_window,
                                "results": results,
                            }
                    except Exception:
                        continue
        except Exception:
            pass
        if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql"):
            # Use pgvector distance operator
            head_filter = ""
            params: Dict[str, Any] = {
                "user_id": current_user.id,
                "qvec": str(q_emb),
                "k": k,
            }
            time_filter = ""
            if time_window:
                # parse like "30d" or "7d"; default days
                try:
                    days = int(time_window.rstrip('d'))
                except Exception:
                    days = 30
                time_filter = " AND t.created_at >= NOW() - INTERVAL '" + str(days) + " days'"
            if not time_window:
                # Hot tier default window
                time_filter = " AND t.created_at >= NOW() - INTERVAL '30 days'"
            if heads_list:
                head_filter = " AND e.head = ANY(:heads)"
                params["heads"] = heads_list
            sql = f"""
                SELECT t.id, t.content, t.role, t.created_at, e.head,
                       (e.embedding <=> :qvec) AS distance
                FROM memory_embedding e
                JOIN memory_trace t ON t.id = e.trace_id
                WHERE t.user_id = :user_id
                {head_filter}
                {time_filter}
                ORDER BY e.embedding <=> :qvec
                LIMIT :k
            """
            rows = db.execute(sql_text(sql), params).fetchall()
            for row in rows:
                results.append({
                    "trace_id": row[0],
                    "content": row[1],
                    "role": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "head": row[4],
                    "score": float(row[5]),
                })

            # Expand via edges: include neighbors of top results (1 hop), de-duplicated
            if results:
                top_ids = [r["trace_id"] for r in results[: max(1, min(5, k))]]
                edge_sql = sql_text(
                    """
                    SELECT t.id, t.content, t.role, t.created_at, 'edge' AS head
                    FROM memory_edge me
                    JOIN memory_trace t ON t.id = me.dst
                    WHERE me.src = ANY(:ids) AND t.user_id = :user_id
                    LIMIT :cap
                    """
                )
                edge_rows = db.execute(edge_sql, {"ids": top_ids, "user_id": current_user.id, "cap": k}).fetchall()
                for row in edge_rows:
                    tid = row[0]
                    if tid in seen:
                        continue
                    results.append({
                        "trace_id": tid,
                        "content": row[1],
                        "role": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                        "head": row[4],
                        "score": 0.5
                    })
                    seen.add(tid)
        else:
            # Fallback: naive in-Python cosine similarity over recent items
            import numpy as np  # lazy import
            qv = np.array(q_emb, dtype=float)
            # Fetch recent embeddings to bound computation
            query = db.query(MemoryEmbedding, MemoryTrace).join(MemoryTrace, MemoryTrace.id == MemoryEmbedding.trace_id)
            query = query.filter(MemoryTrace.user_id == current_user.id)
            if heads_list:
                query = query.filter(MemoryEmbedding.head.in_(heads_list))
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
                results.append({
                    "trace_id": mt.id,
                    "content": mt.content,
                    "role": mt.role,
                    "created_at": mt.created_at.isoformat() if mt.created_at else None,
                    "head": head,
                    "score": float(1.0 - sim),  # align with distance-like semantics
                })

        return {
            "query": q,
            "k": k,
            "heads": heads_list,
            "time_window": time_window,
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recall failed: {e}")
    finally:
        db.close()


class ConsolidateRequest(BaseModel):
    day: Optional[str] = None  # ISO date, e.g., 2025-08-31


@router.post("/consolidate")
async def consolidate(payload: ConsolidateRequest = None, current_user=Depends(get_current_user)):
    """One-shot consolidation: create a simple daily summary and temporal edges between same-day traces.
    This is a lightweight stub to be extended with LLM summarization and richer edge extraction.
    """
    from datetime import datetime, timedelta
    db: Session = SessionLocal()
    try:
        if payload and payload.day:
            try:
                day_dt = datetime.fromisoformat(payload.day)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid day format")
        else:
            day_dt = datetime.utcnow() - timedelta(days=1)
        start = day_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        # Fetch traces from that day
        traces = db.query(MemoryTrace).filter(
            MemoryTrace.user_id == current_user.id,
            MemoryTrace.created_at >= start,
            MemoryTrace.created_at < end,
        ).order_by(MemoryTrace.created_at.asc()).all()

        if not traces:
            return {"status": "ok", "message": "No traces to consolidate for day"}

        # Create a basic summary trace
        # Simple heuristic summary for now
        key_phrases = []
        try:
            for t in traces:
                content_low = (t.content or "").lower()
                for kw in ["meeting", "call", "email", "note", "vector", "graph", "habit", "calendar", "document"]:
                    if kw in content_low:
                        key_phrases.append(kw)
            key_phrases = list(dict.fromkeys(key_phrases))[:8]
        except Exception:
            key_phrases = []
        summary_content = (
            f"Daily summary for {start.date()}: {len(traces)} events captured."
            + (f" Key topics: {', '.join(key_phrases)}." if key_phrases else "")
        )
        summary_id = str(uuid.uuid4())
        summary = MemoryTrace(
            id=summary_id,
            user_id=current_user.id,
            content=summary_content,
            role="summary",
            salience=0.5,
            source=json.dumps({"type": "consolidation"}),
            meta=json.dumps({"day": str(start.date())}),
        )
        db.add(summary)

        # Summary embedding
        try:
            emb = await embedding_service.generate_embedding(summary_content)
            if emb:
                me = MemoryEmbedding(
                    trace_id=summary_id,
                    head="semantic",
                    embedding=emb if (PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql")) else json.dumps(emb),
                )
                db.add(me)
        except Exception:
            pass

        # Temporal edges between consecutive items
        from app.main_simple import MemoryEdge
        for a, b in zip(traces, traces[1:]):
            edge = MemoryEdge(src=a.id, dst=b.id, type="temporal", weight=0.1)
            db.merge(edge)
        # Connect summary to day traces
        for t in traces:
            db.merge(MemoryEdge(src=summary_id, dst=t.id, type="summary_of", weight=0.05))
        db.commit()
        return {"status": "ok", "summary_trace": summary_id, "edges_created": max(0, len(traces) - 1)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Consolidation failed: {e}")
    finally:
        db.close()


class ForgetRequest(BaseModel):
    trace_id: str


@router.post("/forget")
async def forget(payload: ForgetRequest, current_user=Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        trace = db.query(MemoryTrace).filter(MemoryTrace.id == payload.trace_id, MemoryTrace.user_id == current_user.id).first()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        db.query(MemoryEmbedding).filter(MemoryEmbedding.trace_id == payload.trace_id).delete()
        db.delete(trace)
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
        raise HTTPException(status_code=500, detail=f"Failed to delete trace: {e}")
    finally:
        db.close()
