"""
memory.recall() — the one recall API (ONE_MIND §3.4).

Sara has ~18 memory stores and at least three incompatible confidence schemes;
chat context assembly, deliberation, the daemon, and the briefs each read their
own subset, so there is no single "what does Sara know about X?" call. This
module is that call: one fan-out across episodes, notes, documents, summaries,
facts (PKG), people, and open threads, returning traces on **one shape**, with
**one provenance** and **one graduated confidence scale**:

    observed  — it happened / was said (episodes, threads)
    inferred  — derived, not directly stated (summaries, low-confidence facts)
    confirmed — authored or verified (notes, docs, people, confirmed facts)

Additive and safe: it orchestrates the existing per-store search functions
rather than replacing them, so callers can migrate onto the one path
incrementally (recall-paths → 1) without a big-bang cutover.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

ALL_KINDS = ["episode", "note", "document", "summary", "fact", "person", "thread"]

# kind → the search_memory scope that produces it (the multi-store searcher
# already fans over these four).
_KIND_TO_SCOPE = {
    "episode": "episodes",
    "note": "notes",
    "document": "docs",
    "summary": "summaries",
}

# store → graduated confidence tier (single scale, replaces the 3 schemes).
_KIND_CONFIDENCE = {
    "episode": "observed",
    "thread": "observed",
    "summary": "inferred",
    "note": "confirmed",
    "document": "confirmed",
    "person": "confirmed",
    # facts computed per-row from PKG confidence below
}


def _trace(kind: str, id_: Any, text: str, score: float,
           provenance: str, when: Optional[str] = None,
           confidence: Optional[str] = None) -> Dict[str, Any]:
    return {
        "kind": kind,
        "id": str(id_) if id_ is not None else None,
        "text": (text or "").strip()[:600],
        "score": round(float(score or 0.0), 4),
        "confidence": confidence or _KIND_CONFIDENCE.get(kind, "inferred"),
        "provenance": provenance,
        "when": when,
    }


async def _from_search_memory(user_id: str, query: str, kinds: List[str], per: int) -> List[Dict[str, Any]]:
    scopes = [_KIND_TO_SCOPE[k] for k in kinds if k in _KIND_TO_SCOPE]
    if not scopes:
        return []
    try:
        from app.services.memory_service import get_memory_service
        svc = get_memory_service()
        # The multi-store searcher needs a sync session factory; in a bare
        # worker/script the singleton may be uninitialized. Backfill it from
        # the canonical SessionLocal (no-op in the running backend, which sets
        # it at startup).
        if getattr(svc, "SessionLocal", None) is None:
            from app.db.base import SessionLocal
            svc.SessionLocal = SessionLocal
        rows = await svc.search_memory(user_id, query, scopes=scopes, limit=per)
    except Exception as e:
        logger.debug(f"[recall] search_memory failed: {e}")
        return []

    out: List[Dict[str, Any]] = []
    for r in rows or []:
        t = r.get("type") or ""
        kind = {"episode": "episode", "note": "note", "doc": "document",
                "document": "document", "summary": "summary"}.get(t, t)
        text = r.get("text") or r.get("title") or r.get("content") or ""
        out.append(_trace(
            kind=kind,
            id_=r.get("episode_id") or r.get("note_id") or r.get("id") or r.get("doc_id"),
            text=text,
            score=r.get("score", 0.5),
            provenance=f"store:{kind}:{r.get('source','')}".rstrip(":"),
            when=r.get("created_at") or r.get("updated_at"),
        ))
    return out


async def _from_facts(query: str, per: int) -> List[Dict[str, Any]]:
    try:
        from app.services.personal_knowledge_graph import personal_kg
        rows = await personal_kg.query_semantic(query, limit=per)
    except Exception as e:
        logger.debug(f"[recall] fact query_semantic failed: {e}")
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        sim = float(r.get("similarity", 0.0) or 0.0)
        conf = float(r.get("confidence", 0.0) or 0.0)
        tier = "confirmed" if conf >= 0.75 else ("inferred" if conf >= 0.4 else "observed")
        out.append(_trace(
            kind="fact",
            id_=r.get("pkg_id") or r.get("id"),
            text=r.get("content_text") or r.get("content") or "",
            score=sim,
            provenance=f"pkg:{r.get('node_type','fact')}",
            confidence=tier,
        ))
    return out


async def _from_people(user_id: str, query: str, per: int) -> List[Dict[str, Any]]:
    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        factory = get_async_session_factory()
        async with factory() as db:
            rows = (await db.execute(text("""
                SELECT id, canonical_name, notes, importance, last_interaction_at
                FROM person
                WHERE user_id = :uid
                  AND (canonical_name ILIKE :q OR COALESCE(notes,'') ILIKE :q
                       OR EXISTS (SELECT 1 FROM unnest(COALESCE(aliases, ARRAY[]::text[])) a WHERE a ILIKE :q))
                ORDER BY importance DESC NULLS LAST, last_interaction_at DESC NULLS LAST
                LIMIT :lim
            """), {"uid": user_id, "q": f"%{query}%", "lim": per})).mappings().all()
    except Exception as e:
        logger.debug(f"[recall] people search failed: {e}")
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        name = r["canonical_name"] or "someone"
        note = (r["notes"] or "").strip()
        out.append(_trace(
            kind="person",
            id_=r["id"],
            text=f"{name}" + (f" — {note}" if note else ""),
            score=0.6 + min(float(r["importance"] or 0) / 100.0, 0.3),
            provenance="person",
            when=r["last_interaction_at"].isoformat() if r["last_interaction_at"] else None,
        ))
    return out


async def _from_threads(user_id: str, query: str, per: int) -> List[Dict[str, Any]]:
    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        factory = get_async_session_factory()
        async with factory() as db:
            rows = (await db.execute(text("""
                SELECT id, topic, topic_category, suggested_followup, last_mentioned_at, status
                FROM followup_thread
                WHERE user_id = :uid
                  AND status NOT IN ('resolved', 'dropped')
                  AND (topic ILIKE :q OR COALESCE(suggested_followup,'') ILIKE :q OR COALESCE(original_context,'') ILIKE :q)
                ORDER BY last_mentioned_at DESC NULLS LAST
                LIMIT :lim
            """), {"uid": user_id, "q": f"%{query}%", "lim": per})).mappings().all()
    except Exception as e:
        logger.debug(f"[recall] thread search failed: {e}")
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(_trace(
            kind="thread",
            id_=r["id"],
            text=(r["topic"] or "") + (f" — {r['suggested_followup']}" if r["suggested_followup"] else ""),
            score=0.55,
            provenance=f"thread:{r['topic_category'] or 'open'}",
            when=r["last_mentioned_at"].isoformat() if r["last_mentioned_at"] else None,
        ))
    return out


async def recall(
    user_id: str = DEFAULT_USER_ID,
    query: str = "",
    k: int = 10,
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One call, every store. Returns:
        {"query", "traces": [ {kind,id,text,score,confidence,provenance,when} ],
         "by_kind": {kind: count}, "paths": [stores queried]}
    Every source is best-effort — one store failing never fails the recall."""
    kinds = kinds or ALL_KINDS
    per = max(3, min(k, 20))

    tasks = []
    memory_kinds = [k_ for k_ in kinds if k_ in _KIND_TO_SCOPE]
    if memory_kinds:
        tasks.append(_from_search_memory(user_id, query, memory_kinds, per))
    if "fact" in kinds:
        tasks.append(_from_facts(query, per))
    if "person" in kinds:
        tasks.append(_from_people(user_id, query, per))
    if "thread" in kinds:
        tasks.append(_from_threads(user_id, query, per))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    traces: List[Dict[str, Any]] = []
    for res in results:
        if isinstance(res, Exception):
            logger.debug(f"[recall] source raised: {res}")
            continue
        traces.extend(res or [])

    traces.sort(key=lambda t: t["score"], reverse=True)
    traces = traces[:k]

    by_kind: Dict[str, int] = {}
    for t in traces:
        by_kind[t["kind"]] = by_kind.get(t["kind"], 0) + 1

    return {
        "query": query,
        "traces": traces,
        "by_kind": by_kind,
        "paths": kinds,
    }
