"""Bridge durable world attention into Sara's single ambient cognition loop."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable

from sqlalchemy import or_, select

from app.models.world_model import WorldAttentionItem
from app.services.world_state.writer import append_world_event_async

OBSERVATION_PREFIX = "worldattn:"


async def mirror_pending_attention(user_id: str, *, limit: int = 30) -> Dict[str, int]:
    from app.db.session import get_async_session_factory
    from app.services.observation_log import log_observation

    now = datetime.now(timezone.utc)
    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(
            select(WorldAttentionItem)
            .where(
                WorldAttentionItem.user_id == str(user_id),
                WorldAttentionItem.status == "queued",
                or_(WorldAttentionItem.valid_until.is_(None), WorldAttentionItem.valid_until > now),
            )
            .order_by(WorldAttentionItem.aggregate_score.desc(), WorldAttentionItem.last_seen_at.asc())
            .limit(max(1, min(int(limit), 100)))
        )).scalars().all()

    for row in rows:
        await log_observation(
            str(user_id),
            row.description,
            salience=float(row.aggregate_score or 0.0),
            source="world_state",
            category=row.domain,
            observation_id=f"{OBSERVATION_PREFIX}{row.id}",
        )
    return {"mirrored": len(rows)}


async def resolve_attention_observations(user_id: str, observation_ids: Iterable[str]) -> int:
    ids = [str(value)[len(OBSERVATION_PREFIX):] for value in observation_ids if str(value).startswith(OBSERVATION_PREFIX)]
    if not ids:
        return 0
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as db:
        rows = (await db.execute(select(WorldAttentionItem).where(
            WorldAttentionItem.user_id == str(user_id),
            WorldAttentionItem.id.in_(ids),
            WorldAttentionItem.status == "queued",
        ).with_for_update())).scalars().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "resolved"
            row.resolved_at = now
        await db.commit()
    return len(rows)


async def record_cognition_event(
    user_id: str, *, kind: str, turn_id: str, wake_reason: str,
    headline: str, detail: str | None = None, payload: dict | None = None,
) -> None:
    from app.db.session import get_async_session_factory

    factory = get_async_session_factory()
    async with factory() as db:
        await append_world_event_async(
            db,
            user_id=str(user_id),
            kind=kind,
            source="kernel",
            source_ref=turn_id,
            aggregate_type="cognition_turn",
            aggregate_id=turn_id,
            actor_type="model",
            correlation_id=turn_id,
            dedupe_key=f"kernel:{turn_id}:{kind}",
            payload={
                "headline": headline,
                "detail": detail,
                "wake_reason": wake_reason,
                **(payload or {}),
            },
            sensitivity="private",
        )
        await db.commit()
