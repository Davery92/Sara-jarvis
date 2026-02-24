from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import json
import uuid
import time
import re
import os as _os
import httpx

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
    # Generate embeddings per head (best-effort). If embedding fails, still store the trace.
    q_embeddings: Dict[str, List[float]] = {}
    for h in heads:
        try:
            emb = await embedding_service.generate_embedding(payload.content)
        except Exception:
            emb = None
        if not emb:
            # Best-effort: skip embeddings if service is unavailable
            continue
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
                       (e.embedding <=> :qvec::vector) AS distance
                FROM memory_embedding e
                JOIN memory_trace t ON t.id = e.trace_id
                WHERE t.user_id = :user_id
                {head_filter}
                {time_filter}
                ORDER BY e.embedding <=> :qvec::vector
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


_TOKEN_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "have", "your", "what",
    "when", "where", "will", "would", "could", "should", "about", "into",
    "after", "before", "while", "there", "their", "were", "been", "then",
    "just", "need", "today", "tomorrow", "yesterday",
}
_OPEN_LOOP_HINTS = (
    "todo", "to do", "follow up", "remember to", "need to", "should",
    "must", "check", "later", "tomorrow", "next", "deadline", "reminder",
)
_CLOSURE_HINTS = (
    "done", "completed", "finished", "sent", "resolved", "closed",
    "scheduled", "updated", "delivered", "fixed",
)


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return {t for t in tokens if t not in _TOKEN_STOPWORDS}


def _keyword_summary(traces: List[Any], day_label: str) -> str:
    keywords = [
        "meeting", "call", "email", "note", "calendar", "document",
        "task", "decision", "project", "deadline", "reminder", "plan",
    ]
    found: List[str] = []
    for trace in traces:
        content = (trace.content or "").lower()
        for kw in keywords:
            if kw in content:
                found.append(kw)
    topics = list(dict.fromkeys(found))[:8]
    summary = f"Daily summary for {day_label}: {len(traces)} events captured."
    if topics:
        summary += f" Key topics: {', '.join(topics)}."
    return summary


async def _generate_daily_summary(traces: List[Any], day_label: str) -> tuple[str, Dict[str, Any]]:
    from app.core.config import settings

    fallback = _keyword_summary(traces, day_label)
    sample = "\n".join(
        f"- [{(t.role or 'unknown')}] {(t.content or '').strip()[:280]}"
        for t in traces[:30]
    )
    prompt = (
        f"Create a concise daily memory summary for {day_label}.\n"
        "Focus on decisions, commitments, notable events, and unresolved follow-ups.\n"
        "Write 3-5 sentences in plain text.\n\n"
        f"Entries ({len(traces)}):\n{sample}"
    )

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                json={
                    "model": settings.openai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 280,
                },
                headers={"Authorization": f"Bearer {settings.openai_api_key}"} if settings.openai_api_key else {},
            )
            response.raise_for_status()
            data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if len(content) < 40:
                return fallback, {
                    "mode": "fallback",
                    "model": "keyword_fallback",
                    "fallback_reason": "llm_summary_too_short",
                    "baseline_chars": len(fallback),
                }

            return content, {
                "mode": "llm",
                "model": settings.openai_model,
                "fallback_reason": None,
                "baseline_chars": len(fallback),
            }
    except Exception as e:
        return fallback, {
            "mode": "fallback",
            "model": "keyword_fallback",
            "fallback_reason": str(e)[:200],
            "baseline_chars": len(fallback),
        }


def _build_semantic_edges(traces: List[Any], max_edges: int = 80) -> List[tuple[str, str, str, float]]:
    edges: List[tuple[str, str, str, float]] = []
    token_cache = [_tokenize(t.content or "") for t in traces]
    n = len(traces)

    for i in range(n):
        if len(edges) >= max_edges:
            break
        if not token_cache[i]:
            continue

        for j in range(i + 1, min(n, i + 16)):
            if len(edges) >= max_edges:
                break
            if not token_cache[j]:
                continue

            overlap = token_cache[i].intersection(token_cache[j])
            if len(overlap) < 3:
                continue

            union = token_cache[i].union(token_cache[j])
            score = len(overlap) / max(1, len(union))
            if score < 0.23:
                continue

            weight = round(min(0.9, 0.2 + score), 3)
            edges.append((traces[i].id, traces[j].id, "semantic_similarity", weight))

    return edges


def _build_open_loop_edges(
    traces: List[Any],
    summary_id: str,
    max_edges: int = 50,
) -> tuple[List[tuple[str, str, str, float]], int]:
    edges: List[tuple[str, str, str, float]] = []
    unresolved = 0
    token_cache = [_tokenize(t.content or "") for t in traces]

    def _contains(text: str, hints: tuple[str, ...]) -> bool:
        lower = (text or "").lower()
        return any(h in lower for h in hints)

    for i, trace in enumerate(traces):
        if len(edges) >= max_edges:
            break
        content = trace.content or ""
        if not _contains(content, _OPEN_LOOP_HINTS):
            continue

        source_tokens = token_cache[i]
        followup_id = None
        for j in range(i + 1, min(len(traces), i + 20)):
            candidate_content = traces[j].content or ""
            overlap = source_tokens.intersection(token_cache[j]) if source_tokens else set()
            if _contains(candidate_content, _CLOSURE_HINTS) and (len(overlap) >= 1 or not source_tokens):
                followup_id = traces[j].id
                break

        if followup_id:
            edges.append((trace.id, followup_id, "open_loop_followup", 0.45))
        else:
            edges.append((trace.id, summary_id, "open_loop_carry_forward", 0.4))
            unresolved += 1

    return edges, unresolved


@router.post("/consolidate")
async def consolidate(payload: ConsolidateRequest = None, current_user=Depends(get_current_user)):
    """
    Consolidate one day of memories with LLM summary + richer edge extraction.
    """
    from datetime import datetime, timedelta
    from app.main_simple import MemoryEdge

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

        day_label = str(start.date())
        summary_content, summary_info = await _generate_daily_summary(traces, day_label)
        summary_id = str(uuid.uuid4())
        summary = MemoryTrace(
            id=summary_id,
            user_id=current_user.id,
            content=summary_content,
            role="summary",
            salience=0.5,
            source=json.dumps({
                "type": "consolidation",
                "producer": "memory_route_v2",
                "provenance": {
                    "summary_mode": summary_info["mode"],
                    "summary_model": summary_info["model"],
                },
            }),
            meta=json.dumps({
                "day": day_label,
                "consolidation_version": "v2",
                "trace_count": len(traces),
                "summary_mode": summary_info["mode"],
                "summary_model": summary_info["model"],
                "fallback_reason": summary_info.get("fallback_reason"),
                "baseline_chars": summary_info.get("baseline_chars"),
            }),
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

        all_edges: List[tuple[str, str, str, float]] = []
        for a, b in zip(traces, traces[1:]):
            all_edges.append((a.id, b.id, "temporal_continuity", 0.15))

        all_edges.extend(_build_semantic_edges(traces))

        open_loop_edges, unresolved_open_loops = _build_open_loop_edges(traces, summary_id)
        all_edges.extend(open_loop_edges)

        for t in traces:
            all_edges.append((summary_id, t.id, "summary_of", 0.05))

        deduped_edges: Dict[tuple[str, str, str], float] = {}
        for src, dst, edge_type, weight in all_edges:
            key = (src, dst, edge_type)
            if key not in deduped_edges or weight > deduped_edges[key]:
                deduped_edges[key] = weight

        for (src, dst, edge_type), weight in deduped_edges.items():
            db.merge(MemoryEdge(src=src, dst=dst, type=edge_type, weight=weight))

        db.commit()

        edge_counts: Dict[str, int] = {}
        for _, _, edge_type in deduped_edges.keys():
            edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1

        return {
            "status": "ok",
            "summary_trace": summary_id,
            "summary_mode": summary_info["mode"],
            "summary_model": summary_info["model"],
            "traces_consolidated": len(traces),
            "edges_created": len(deduped_edges),
            "edge_counts": edge_counts,
            "quality_checks": {
                "fallback_used": summary_info["mode"] != "llm",
                "fallback_reason": summary_info.get("fallback_reason"),
                "unresolved_open_loops": unresolved_open_loops,
                "semantic_edges": edge_counts.get("semantic_similarity", 0),
                "temporal_edges": edge_counts.get("temporal_continuity", 0),
            },
        }
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
        from app.models.memory_trace import MemoryEdge

        trace = db.query(MemoryTrace).filter(MemoryTrace.id == payload.trace_id, MemoryTrace.user_id == current_user.id).first()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        db.query(MemoryEmbedding).filter(MemoryEmbedding.trace_id == payload.trace_id).delete()
        db.query(MemoryEdge).filter(
            (MemoryEdge.src == payload.trace_id) | (MemoryEdge.dst == payload.trace_id)
        ).delete(synchronize_session=False)
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
