"""Candidate queue primitives (SARA_MIND_V2 §3.5). Dark infrastructure —
nothing calls `create_candidate()` yet (Phase 2's direct-sender conversion
table in the plan §6 hasn't been wired). This module exists so the purge
sweep and TTL guarantee are live and provable before a single candidate
is ever created, per principle #5: "mechanical expiry beats reasoning."

TTL defaults by kind (§3.5): prep -> event start (caller supplies
valid_until explicitly since only the caller knows the event time);
alert -> 30 min; inform -> 24h; followup -> thread window (caller
supplies); retrospective -> 12h.
"""
import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

_DEFAULT_TTL = {
    "alert": timedelta(minutes=30),
    "inform": timedelta(hours=24),
    "retrospective": timedelta(hours=12),
    # 'prep' and 'followup' have no safe default — the caller must pass
    # valid_until explicitly (event start / thread window).
}

_KINDS = ("inform", "followup", "prep", "alert", "retrospective")


async def create_candidate(
    db,
    user_id: str,
    source: str,
    kind: str,
    summary: str,
    evidence: Optional[List[Any]] = None,
    topic_entities: Optional[List[str]] = None,
    value_guess: Optional[float] = None,
    valid_until=None,
    dedupe_key: Optional[str] = None,
) -> Optional[UUID]:
    """`dedupe_key` (Mind V2 rewire plan, Workstream B) is the SAME stable
    identity a sender already uses for its notification topic — e.g.
    `xref:{email_id}:{event_id}` — passed through so the same underlying
    event never produces two live candidates just because a sender fired
    twice. Duplicates die structurally here (return None, no row created)
    rather than relying on the judge's LLM to notice a repeat in its
    context window. Stored as topic_entities[0] so it survives without a
    schema change."""
    if kind not in _KINDS:
        raise ValueError(f"unknown candidate kind: {kind!r}")
    if valid_until is None:
        default = _DEFAULT_TTL.get(kind)
        if default is None:
            raise ValueError(f"kind={kind!r} has no default TTL — valid_until is required")
        valid_until = local_now() + default

    if dedupe_key:
        existing = (await db.execute(text("""
            SELECT id FROM say_candidate
            WHERE user_id = :uid AND source = :source
              AND :dedupe_key = ANY(topic_entities)
              AND valid_until >= NOW()
            LIMIT 1
        """), {"uid": user_id, "source": source, "dedupe_key": dedupe_key})).first()
        if existing:
            logger.debug(
                f"[say_candidate] duplicate suppressed dedupe_key={dedupe_key!r} source={source!r}"
            )
            return None

    topics = list(topic_entities or [])
    if dedupe_key and dedupe_key not in topics:
        topics.insert(0, dedupe_key)

    row = (await db.execute(text("""
        INSERT INTO say_candidate
            (user_id, source, kind, topic_entities, summary, evidence, value_guess, valid_until)
        VALUES
            (:uid, :source, :kind, :topics, :summary, CAST(:evidence AS jsonb), :value_guess, :valid_until)
        RETURNING id
    """), {
        "uid": user_id, "source": source, "kind": kind,
        "topics": topics, "summary": summary,
        "evidence": json.dumps(evidence or []),
        "value_guess": value_guess, "valid_until": valid_until,
    })).first()
    await db.commit()
    return row.id


async def purge_expired(db, user_id: str = DEFAULT_USER_ID) -> int:
    """The mechanical guarantee (§3.5): an expired candidate becomes
    unreachable by the judge. Run every 5 min + before every judge run."""
    result = await db.execute(text("""
        UPDATE say_candidate
        SET status = 'expired'
        WHERE user_id = :uid AND status = 'pending' AND valid_until < NOW()
    """), {"uid": user_id})
    await db.commit()
    return result.rowcount or 0


async def pending_candidates(db, user_id: str = DEFAULT_USER_ID, limit: int = 50) -> List[Dict[str, Any]]:
    """Post-purge pending candidates, newest first. The judge's input."""
    rows = (await db.execute(text("""
        SELECT id, source, kind, topic_entities, summary, evidence, value_guess,
               valid_until, created_at
        FROM say_candidate
        WHERE user_id = :uid AND status = 'pending' AND valid_until >= NOW()
        ORDER BY value_guess DESC NULLS LAST, created_at DESC
        LIMIT :limit
    """), {"uid": user_id, "limit": limit})).fetchall()
    return [
        {
            "id": str(r.id), "source": r.source, "kind": r.kind,
            "topic_entities": list(r.topic_entities or []), "summary": r.summary,
            "evidence": r.evidence, "value_guess": r.value_guess,
            "valid_until": r.valid_until.isoformat() if r.valid_until else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
