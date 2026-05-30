"""Narrator coordinator — the glue that turns observations into utterances.

Single sweep flow:
    for each registered trigger:
        ctx = trigger.check(db, user_id)
        if not ctx: continue
        if cooldown is hot for ctx.dedup_key: continue
        utterance = voice.generate(ctx, recent_events)
        publish SystemEvent via narrator.bus
        mark cooldown

This file does NOT handle per-surface delivery (PR 3 desktop, PR 4 iOS).
It just produces and publishes the durable event; surfaces subscribe to the
SYSTEM_NARRATION_EMITTED bus topic and the /api/narrator/events endpoint.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.narrator import bus as narrator_bus
from app.services.narrator import delivery, dispatch, voice
from app.services.narrator.triggers import registry as trigger_registry
from app.services.narrator.triggers.base import Trigger, TriggerContext

logger = logging.getLogger(__name__)


RECENT_EVENTS_FOR_PROMPT = 5


async def _load_recent_events(
    db: AsyncSession, user_id: str, limit: int
) -> List[Dict[str, Any]]:
    """Last N events for anti-repetition context. Suppressed events count
    too — the model should still avoid reusing phrasings from silent ones."""
    result = await db.execute(
        text(
            """
            SELECT title, body, severity, trigger_name, created_at
            FROM system_event
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"user_id": user_id, "limit": limit},
    )
    rows = result.mappings().all()
    # Reverse so oldest-of-the-recent appears first in the prompt — reads
    # more naturally to the model as a timeline.
    return [
        {
            "title": r["title"],
            "body": r["body"],
            "severity": r["severity"],
            "trigger_name": r["trigger_name"],
        }
        for r in reversed(rows)
    ]


async def fire_trigger(
    trigger: Trigger,
    db: AsyncSession,
    user_id: str,
    *,
    bypass_cooldown: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run a single trigger end-to-end. Returns a result dict (for logging
    and admin endpoints) or None if the trigger didn't fire.

    Result keys: trigger_name, status, event_id (if emitted), reason.
    """
    name = trigger.name
    ctx = await trigger.check(db, user_id)
    if ctx is None:
        return {"trigger_name": name, "status": "no_match"}

    dedup_key = ctx.effective_dedup_key()
    if not bypass_cooldown and await dispatch.is_on_cooldown(dedup_key):
        return {
            "trigger_name": name,
            "status": "cooldown",
            "dedup_key": dedup_key,
        }

    recent = await _load_recent_events(db, user_id, RECENT_EVENTS_FOR_PROMPT)
    utterance = await voice.generate(ctx, recent_events=recent)

    payload = narrator_bus.SystemEventPayload(
        user_id=user_id,
        type=ctx.severity,
        title=utterance.title,
        body=utterance.body,
        subtitle=utterance.subtitle,
        severity=ctx.severity,
        trigger_name=ctx.trigger_name,
        trigger_context=ctx.facts,
        suppressed=False,
    )
    await narrator_bus.publish(payload, db=db)
    await dispatch.mark_fired(dedup_key, trigger.cooldown_seconds)

    delivered = await delivery.dispatch(payload, db=db)

    return {
        "trigger_name": name,
        "status": "emitted",
        "event_id": str(payload.id) if payload.id else None,
        "dedup_key": dedup_key,
        "fell_back": utterance.fell_back,
        "retried": utterance.retried,
        "delivered_to": delivered,
    }


async def sweep_all(
    db: AsyncSession,
    user_id: str,
    *,
    bypass_cooldown: bool = False,
    only: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Run every registered trigger once. `only` restricts to a subset
    (handy for admin endpoints + tests)."""
    results: List[Dict[str, Any]] = []
    selected = trigger_registry if only is None else {
        n: t for n, t in trigger_registry.items() if n in only
    }
    for name, trigger in sorted(selected.items()):
        try:
            r = await fire_trigger(
                trigger, db, user_id, bypass_cooldown=bypass_cooldown
            )
            if r is not None:
                results.append(r)
        except Exception as exc:
            logger.exception("narrator: trigger %s crashed", name)
            results.append(
                {"trigger_name": name, "status": "error", "error": str(exc)}
            )
            # A SQL error in one trigger's check() leaves the AsyncSession in
            # "current transaction is aborted" state — every subsequent query
            # in the same sweep would fail until we rollback. Roll back so
            # the next trigger gets a clean slate.
            try:
                await db.rollback()
            except Exception:
                pass
    return results
