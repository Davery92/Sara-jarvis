"""ACS v2 interests — Sara's persistent interests, weighted and decaying.

Backed by sara_interest (migration 063). The daemon writes here during
reflection consolidation; idle ticks read here to seed self-authored
sara_inbox items so she pursues her interests when David's queue is empty.

Semantic dedup: an upsert with a near-duplicate (cosine ≥ DEDUP_SIMILARITY)
merges into the existing row instead of creating a new one. This keeps the
table tight as she reframes the same idea across reflection cycles.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import get_current_user, get_current_user_optional
from app.db.session import get_async_session_factory
from app.models.user import User
from app.routes.acs_daemon import verify_daemon_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/acs/v2/interests", tags=["ACS v2 — interests"])


# Cosine similarity threshold for "this is the same interest she's already
# tracking, just phrased differently." Above this, upserts merge in place.
# Calibrated for bge-m3 on short topic strings: paraphrases of the same idea
# typically land in the 0.55–0.80 range (e.g. "RAG evaluation pitfalls" vs
# "retrieval-augmented generation evaluation problems" → 0.60). Pushing higher
# than ~0.72 fails to dedup obvious rephrasings; lower than ~0.55 starts merging
# adjacent-but-distinct topics.
DEDUP_SIMILARITY = 0.55


# ── Schemas ───────────────────────────────────────────────────────────────────

class InterestOut(BaseModel):
    id: str
    topic: str
    display_name: str
    why: Optional[str]
    weight: float
    last_acted_at: Optional[datetime]
    last_updated_at: datetime
    source: str
    created_at: datetime
    blocked: bool = False


class InterestUpsertIn(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    why: Optional[str] = Field(None, max_length=2000)
    weight_delta: float = Field(1.0, ge=-100.0, le=100.0)
    source: str = Field("reflection", pattern="^(reflection|external_event|manual)$")


class InterestUpsertOut(BaseModel):
    interest: InterestOut
    merged: bool
    # True when the upsert matched a topic David has blocked: nothing was
    # written, and the caller should treat the topic as off-limits.
    blocked: bool = False


class DecayOut(BaseModel):
    factor: float
    rows_affected: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_topic(name: str) -> str:
    return " ".join(name.lower().strip().split())


def _row_to_interest(row: dict) -> InterestOut:
    return InterestOut(
        id=str(row["id"]),
        topic=row["topic"],
        display_name=row["display_name"],
        why=row["why"],
        weight=float(row["weight"]),
        last_acted_at=row["last_acted_at"],
        last_updated_at=row["last_updated_at"],
        source=row["source"],
        created_at=row["created_at"],
        blocked=bool(row.get("blocked", False)),
    )


def _check_auth(x_daemon_token: Optional[str], current_user: Optional[User]) -> None:
    expected = getattr(settings, "acs_daemon_token", None) or ""
    is_daemon = bool(expected and x_daemon_token == expected)
    if not is_daemon and current_user is None:
        raise HTTPException(status_code=401, detail="auth required")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[InterestOut])
async def list_interests(
    limit: int = Query(50, ge=1, le=500),
    min_weight: float = Query(0.0, ge=0.0),
    stale_hours: Optional[int] = Query(
        None, ge=0, le=24 * 90,
        description="If set, only return rows with last_acted_at older than this (or NULL)",
    ),
    include_blocked: bool = Query(
        False,
        description="Include topics David has blocked (UI curation only — "
                    "never set for daemon context).",
    ),
    x_daemon_token: Optional[str] = Header(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> list[InterestOut]:
    _check_auth(x_daemon_token, current_user)

    where = ["weight >= :min_weight"]
    if not include_blocked:
        where.append("NOT blocked")
    params: dict[str, Any] = {"limit": limit, "min_weight": min_weight}
    if stale_hours is not None:
        where.append(
            "(last_acted_at IS NULL "
            "OR last_acted_at < NOW() - make_interval(hours => :stale_hours))"
        )
        params["stale_hours"] = stale_hours

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(
            text(
                f"""
                SELECT id, topic, display_name, why, weight, last_acted_at,
                       last_updated_at, source, created_at, blocked
                FROM sara_interest
                WHERE {' AND '.join(where)}
                ORDER BY weight DESC, last_updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )).mappings().all()
    return [_row_to_interest(dict(r)) for r in rows]


@router.post("", response_model=InterestUpsertOut,
             dependencies=[Depends(verify_daemon_token)])
async def upsert_interest(payload: InterestUpsertIn) -> InterestUpsertOut:
    """Upsert an interest. Tries exact-topic match first, then semantic match
    via embedding cosine similarity; if either hits, bumps weight on the
    existing row instead of creating a duplicate. `why` is appended (deduped)
    rather than overwritten so we keep the trail of reasons she's developed
    for caring."""
    topic = _normalize_topic(payload.display_name)

    embed_text = payload.display_name + (("\n\n" + payload.why) if payload.why else "")
    vec: Optional[list[float]] = None
    try:
        from app.services.embeddings import get_embedding
        vec = await get_embedding(embed_text)
    except Exception as e:
        logger.warning(f"interest embedding failed: {e}")

    async_session = get_async_session_factory()
    async with async_session() as db:
        existing = (await db.execute(
            text(
                """
                SELECT id, topic, display_name, why, weight, last_acted_at,
                       last_updated_at, source, created_at, blocked
                FROM sara_interest WHERE topic = :topic
                """
            ),
            {"topic": topic},
        )).mappings().first()

        if not existing and vec is not None:
            row = (await db.execute(
                text(
                    """
                    SELECT id, topic, display_name, why, weight, last_acted_at,
                           last_updated_at, source, created_at, blocked,
                           1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                    FROM sara_interest
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector) ASC
                    LIMIT 1
                    """
                ),
                {"vec": str(vec)},
            )).mappings().first()
            if row and float(row.get("similarity") or 0.0) >= DEDUP_SIMILARITY:
                existing = row

        if existing and existing.get("blocked"):
            # David blocked this topic. The row stays as a semantic tombstone
            # so rephrasings land here too — nothing is bumped or appended.
            logger.info(
                "interest upsert rejected (blocked topic): %r matched %r",
                payload.display_name, existing["display_name"],
            )
            return InterestUpsertOut(
                interest=_row_to_interest(dict(existing)),
                merged=True,
                blocked=True,
            )

        if existing:
            new_why = existing["why"]
            if payload.why and (not new_why or payload.why.lower() not in new_why.lower()):
                new_why = (new_why + " | " + payload.why) if new_why else payload.why
                if len(new_why) > 4000:
                    new_why = new_why[-4000:]
            row = (await db.execute(
                text(
                    """
                    UPDATE sara_interest
                    SET weight = weight + :delta,
                        why = :why,
                        last_updated_at = NOW(),
                        embedding = COALESCE(CAST(:vec AS vector), embedding)
                    WHERE id = :id
                    RETURNING id, topic, display_name, why, weight, last_acted_at,
                              last_updated_at, source, created_at, blocked
                    """
                ),
                {
                    "delta": payload.weight_delta,
                    "why": new_why,
                    "vec": str(vec) if vec is not None else None,
                    "id": existing["id"],
                },
            )).mappings().first()
            await db.commit()
            return InterestUpsertOut(interest=_row_to_interest(dict(row)), merged=True)

        row = (await db.execute(
            text(
                """
                INSERT INTO sara_interest
                    (topic, display_name, why, weight, source, embedding)
                VALUES
                    (:topic, :display_name, :why, :weight, :source, CAST(:vec AS vector))
                RETURNING id, topic, display_name, why, weight, last_acted_at,
                          last_updated_at, source, created_at, blocked
                """
            ),
            {
                "topic": topic,
                "display_name": payload.display_name,
                "why": payload.why,
                "weight": max(payload.weight_delta, 0.1),
                "source": payload.source,
                "vec": str(vec) if vec is not None else None,
            },
        )).mappings().first()
        await db.commit()
        return InterestUpsertOut(interest=_row_to_interest(dict(row)), merged=False)


@router.post("/{interest_id}/bump", response_model=InterestOut,
             dependencies=[Depends(verify_daemon_token)])
async def bump_interest(
    interest_id: str,
    delta: float = Query(1.0, ge=-100.0, le=100.0),
) -> InterestOut:
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_interest
                SET weight = GREATEST(0.0, weight + :delta),
                    last_updated_at = NOW()
                WHERE id = :id
                RETURNING id, topic, display_name, why, weight, last_acted_at,
                          last_updated_at, source, created_at, blocked
                """
            ),
            {"delta": delta, "id": interest_id},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="interest not found")
    return _row_to_interest(dict(row))


@router.post("/{interest_id}/touch", response_model=InterestOut,
             dependencies=[Depends(verify_daemon_token)])
async def touch_interest(interest_id: str) -> InterestOut:
    """Mark that she opened a session on this interest. Sets last_acted_at=NOW()
    so the idle-seeding query won't re-pick it until it goes stale again."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_interest
                SET last_acted_at = NOW(), last_updated_at = NOW()
                WHERE id = :id
                RETURNING id, topic, display_name, why, weight, last_acted_at,
                          last_updated_at, source, created_at, blocked
                """
            ),
            {"id": interest_id},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="interest not found")
    return _row_to_interest(dict(row))


@router.post("/decay", response_model=DecayOut,
             dependencies=[Depends(verify_daemon_token)])
async def decay_interests(
    factor: float = Query(0.95, gt=0.0, le=1.0),
) -> DecayOut:
    """Multiply all weights by `factor`. Run once a day so dormant interests
    fade. Factor of 0.95 → ~50% half-life ~14 days."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text("UPDATE sara_interest SET weight = weight * :factor WHERE weight > 0.01"),
            {"factor": factor},
        )
        await db.commit()
    return DecayOut(factor=factor, rows_affected=result.rowcount or 0)


@router.post("/{interest_id}/block", response_model=InterestOut)
async def block_interest(
    interest_id: str,
    blocked: bool = Query(True, description="False to lift the block."),
    current_user: User = Depends(get_current_user),
) -> InterestOut:
    """David vetoes a topic for good. Unlike delete, the row survives as a
    semantic tombstone: reflection re-adds merge into it via embedding dedup
    and get rejected, so the topic stays dead instead of resurrecting."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        row = (await db.execute(
            text(
                """
                UPDATE sara_interest
                SET blocked = :blocked,
                    weight = CASE WHEN :blocked THEN 0.0 ELSE weight END,
                    last_updated_at = NOW()
                WHERE id = :id
                RETURNING id, topic, display_name, why, weight, last_acted_at,
                          last_updated_at, source, created_at, blocked
                """
            ),
            {"id": interest_id, "blocked": blocked},
        )).mappings().first()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="interest not found")
    return _row_to_interest(dict(row))


@router.delete("/{interest_id}")
async def delete_interest(
    interest_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """David prunes interests he doesn't want her pursuing. NOTE: reflection
    can re-create a deleted topic from scratch — for a veto that sticks, use
    POST /{interest_id}/block instead."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text("DELETE FROM sara_interest WHERE id = :id"),
            {"id": interest_id},
        )
        await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="interest not found")
    return {"deleted": interest_id}
