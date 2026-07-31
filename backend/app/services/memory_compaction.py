"""Memory compaction / forgetting — Brain Alignment H4.

Sleep consolidates the gist into semantic memory and lets the rest decay.
Forgetting is a feature: it's what keeps retrieval sharp. This job finds old,
low-importance, never-retrieved episodes, compresses each topic/week cluster
into ONE `semantic_summary` row (plus durable PKG facts), and — once David
enables it — deletes the source episodes, keeping a tombstone count.

SAFETY: irreversible deletion is gated behind the tunable
`memory.forgetting_delete_enabled` (default False). Until UNLEASHED I.1's
golden retrieval set exists to prove recall doesn't regress, this runs in
dry-run: it still writes the gist (summary + PKG facts) and marks sources
`consolidated=true`, but keeps the rows. Flip the tunable to actually forget.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

FORGET_AGE_DAYS = 90
FORGET_IMPORTANCE_MAX = 0.15
FORGET_NO_ACCESS_DAYS = 60
MIN_CLUSTER = 3
MAX_CANDIDATES_PER_RUN = 2000
MAX_DELETE_PER_RUN = 500


def _topic_of(topics_raw: Any) -> str:
    """First topic tag, or 'general'."""
    try:
        t = topics_raw if isinstance(topics_raw, list) else json.loads(topics_raw or "[]")
        if isinstance(t, list) and t:
            return str(t[0]).lower()[:40]
    except Exception:
        pass
    return "general"


async def compact_old_memories(user_id: str = DEFAULT_USER_ID) -> Dict[str, Any]:
    """Compress stale low-value episodes into semantic summaries + PKG facts.
    Deletes sources only if forgetting is enabled; otherwise dry-run."""
    from app.db.base import SessionLocal
    from app.services.tunables import get_tunable_bool

    delete_enabled = get_tunable_bool("memory.forgetting_delete_enabled", False)
    stats = {"candidates": 0, "clusters": 0, "summaries_written": 0,
             "episodes_tombstoned": 0, "pkg_facts": 0, "delete_enabled": delete_enabled}

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, content, topics, created_at, role
            FROM episode
            WHERE user_id = :uid
              AND created_at < NOW() - make_interval(days => :age)
              AND COALESCE(importance, 0) < :imp
              AND (last_accessed IS NULL OR last_accessed < NOW() - make_interval(days => :noacc))
              AND COALESCE(consolidated, FALSE) = FALSE
              AND role IN ('user', 'assistant')
            ORDER BY created_at ASC
            LIMIT :lim
        """), {"uid": user_id, "age": FORGET_AGE_DAYS, "imp": FORGET_IMPORTANCE_MAX,
               "noacc": FORGET_NO_ACCESS_DAYS, "lim": MAX_CANDIDATES_PER_RUN}).fetchall()
        stats["candidates"] = len(rows)
        if not rows:
            return stats

        # Cluster by (ISO week, topic).
        clusters: Dict[tuple, List[Any]] = defaultdict(list)
        for r in rows:
            week = r.created_at.strftime("%G-W%V") if r.created_at else "unknown"
            clusters[(week, _topic_of(r.topics))].append(r)

        deleted_budget = MAX_DELETE_PER_RUN
        for (week, topic), members in clusters.items():
            if len(members) < MIN_CLUSTER:
                continue
            stats["clusters"] += 1
            ep_ids = [m.id for m in members]

            summary = await _summarize_cluster(members, week, topic)
            if not summary:
                continue
            embedding = await _embed(summary)
            if not embedding:
                continue

            coverage = {
                "week": week, "topic": topic,
                "episode_count": len(members),
                "episode_ids": ep_ids[:200],
                "tombstoned": bool(delete_enabled),
                "compacted_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute(text("""
                INSERT INTO semantic_summary (id, user_id, scope, summary, embedding, coverage)
                VALUES (:id, :uid, :scope, :summary, CAST(:emb AS vector), CAST(:cov AS jsonb))
            """), {
                "id": str(uuid.uuid4()), "uid": user_id,
                "scope": f"week:{week}:topic:{topic}", "summary": summary,
                "emb": str(embedding), "cov": json.dumps(coverage),
            })
            stats["summaries_written"] += 1

            # Distill anything durable into the PKG before the source is gone.
            try:
                n = await _extract_pkg(members, user_id)
                stats["pkg_facts"] += n
            except Exception as e:
                logger.debug(f"compaction PKG extract failed: {e}")

            # Mark the gist as captured either way; delete only if enabled.
            db.execute(text("UPDATE episode SET consolidated = TRUE WHERE id = ANY(:ids)"),
                       {"ids": ep_ids})
            if delete_enabled and deleted_budget > 0:
                to_delete = ep_ids[:deleted_budget]
                db.execute(text("DELETE FROM episode WHERE id = ANY(:ids)"), {"ids": to_delete})
                deleted_budget -= len(to_delete)
                stats["episodes_tombstoned"] += len(to_delete)
            db.commit()

        logger.info(
            f"[compaction] user={user_id} candidates={stats['candidates']} "
            f"clusters={stats['clusters']} summaries={stats['summaries_written']} "
            f"tombstoned={stats['episodes_tombstoned']} pkg={stats['pkg_facts']} "
            f"delete_enabled={delete_enabled}"
        )
        return stats
    except Exception as e:
        db.rollback()
        logger.error(f"[compaction] failed: {e}")
        stats["error"] = str(e)
        return stats
    finally:
        db.close()


async def _summarize_cluster(members: List[Any], week: str, topic: str) -> str:
    """One-to-three sentence gist of a topic/week cluster."""
    from app.core.llm import get_background_llm_client
    excerpts = "\n".join(f"- {(m.content or '')[:200]}" for m in members[:30])
    prompt = (
        f"These are low-importance conversation fragments about '{topic}' from {week}. "
        "Write a 1–3 sentence factual gist capturing anything worth remembering long-term "
        "(decisions, facts, preferences, outcomes). If nothing is worth keeping, reply exactly 'NOTHING'.\n\n"
        f"{excerpts}"
    )
    try:
        client = get_background_llm_client()
        resp = await client.chat_completion(
            messages=[
                {"role": "system", "content": "You compress memories into a terse factual gist. No preamble."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3, max_tokens=200,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = ""
        if isinstance(resp, dict):
            ch = resp.get("choices", [])
            if ch:
                raw = ch[0].get("message", {}).get("content", "")
        else:
            raw = str(resp)
        raw = (raw or "").strip()
        if not raw or raw.upper().startswith("NOTHING"):
            return ""
        return raw[:1000]
    except Exception as e:
        logger.debug(f"cluster summarize failed: {e}")
        return ""


async def _embed(text_str: str):
    try:
        from app.services.embedding_service import EmbeddingService
        # Background consolidation — presence-latency ruling 1 (2026-07-31):
        # CPU fallback host, never the GPU host a real chat turn needs.
        return await EmbeddingService().generate_embedding(text_str, capability="embedding_cognition")
    except Exception as e:
        logger.debug(f"compaction embed failed: {e}")
        return None


async def _extract_pkg(members: List[Any], user_id: str) -> int:
    """Extract durable PKG facts from a cluster's user turns before deletion."""
    from app.services.pkg_extractor import PKGExtractor
    msgs = [{"role": m.role, "content": m.content or ""} for m in members if m.role == "user"]
    if not msgs:
        return 0
    res = await PKGExtractor().lightweight_extract(msgs, user_id)
    return len(res.get("extracted", []) or [])
