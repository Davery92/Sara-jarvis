"""Narrator admin/test endpoints (PR 1).

Surface area is intentionally small in this PR:
- POST /api/narrator/events/test → synthesize a System AI event (no LLM)
- GET  /api/narrator/events       → recent events (with optional filters)
- GET  /api/narrator/events/{id}  → single event with full trigger_context

The persona, triggers, and per-surface delivery land in later PRs. This file
exists so we can smoke-test the schema, the bus contract, and the row-level
mechanics end-to-end before plugging in the LLM.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.auth import verify_token
from app.core.deps import get_current_user
from app.db.session import get_async_session_factory
from app.models.user import User
from app.services.narrator.bus import (
    VALID_SEVERITIES,
    SystemEventPayload,
    publish,
)
from app.services.narrator import coordinator, delivery, dispatch
from app.services.narrator import scheduled as narrator_scheduled
from app.services.narrator.triggers import registry as trigger_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/narrator", tags=["Narrator"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class TestEventIn(BaseModel):
    """Synthetic narrator event for smoke-testing.

    No LLM is invoked — the caller supplies the title and body directly.
    PR 2 replaces this with a real persona-driven path.
    """

    trigger_name: str = Field(..., max_length=64)
    severity: Literal[
        "roast",
        "observation",
        "achievement",
        "patch_note",
        "sponsored",
        "grudging",
        "deflected",
    ]
    title: str
    body: str
    subtitle: Optional[str] = None
    trigger_context: Dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = 30
    sound: Optional[str] = None
    suppressed: bool = False
    suppression_reason: Optional[str] = None


class SystemEventOut(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    body: str
    subtitle: Optional[str]
    severity: str
    trigger_name: str
    trigger_context: Dict[str, Any]
    ttl_seconds: int
    sound: Optional[str]
    delivered_to: List[str]
    suppressed: bool
    suppression_reason: Optional[str]
    created_at: str


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/events/test", response_model=SystemEventOut)
async def fire_test_event(
    payload: TestEventIn,
    current_user: User = Depends(get_current_user),
) -> SystemEventOut:
    """Persist a synthetic System AI event, publish on the bus, and deliver
    to any connected desktop surfaces.

    No LLM, no trigger detection — useful for smoke-testing the full
    persist → bus → surface fanout in isolation. Suppressed events skip
    delivery, as in production.
    """
    async_session = get_async_session_factory()
    async with async_session() as db:
        event = SystemEventPayload(
            user_id=str(current_user.id),
            type=payload.severity,
            title=payload.title,
            body=payload.body,
            subtitle=payload.subtitle,
            severity=payload.severity,
            trigger_name=payload.trigger_name,
            trigger_context=payload.trigger_context,
            ttl_seconds=payload.ttl_seconds,
            sound=payload.sound,
            suppressed=payload.suppressed,
            suppression_reason=payload.suppression_reason,
        )
        await publish(event, db=db)
        await delivery.dispatch(event, db=db)

    return SystemEventOut(**event.to_dict())


@router.get("/events", response_model=List[SystemEventOut])
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    trigger_name: Optional[str] = None,
    severity: Optional[str] = None,
    include_suppressed: bool = True,
    current_user: User = Depends(get_current_user),
) -> List[SystemEventOut]:
    """Recent System AI events, newest first."""
    if severity is not None and severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid severity; must be one of {list(VALID_SEVERITIES)}",
        )

    clauses = ["user_id = :user_id"]
    params: Dict[str, Any] = {"user_id": str(current_user.id), "limit": limit}
    if trigger_name:
        clauses.append("trigger_name = :trigger_name")
        params["trigger_name"] = trigger_name
    if severity:
        clauses.append("severity = :severity")
        params["severity"] = severity
    if not include_suppressed:
        clauses.append("suppressed = false")

    where = " AND ".join(clauses)
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text(
                f"""
                SELECT id, user_id, type, title, body, subtitle, severity,
                       trigger_name, trigger_context, ttl_seconds, sound,
                       delivered_to, suppressed, suppression_reason, created_at
                FROM system_event
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        rows = result.mappings().all()

    return [_row_to_out(r) for r in rows]


@router.get("/events/{event_id}", response_model=SystemEventOut)
async def get_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SystemEventOut:
    """Single event with full trigger_context (for tap-to-context)."""
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await db.execute(
            text(
                """
                SELECT id, user_id, type, title, body, subtitle, severity,
                       trigger_name, trigger_context, ttl_seconds, sound,
                       delivered_to, suppressed, suppression_reason, created_at
                FROM system_event
                WHERE id = :id AND user_id = :user_id
                """
            ),
            {"id": str(event_id), "user_id": str(current_user.id)},
        )
        row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    return _row_to_out(row)


# ── Trigger admin ────────────────────────────────────────────────────────────


class TriggerInfo(BaseModel):
    name: str
    cooldown_seconds: int
    class_name: str


class SweepIn(BaseModel):
    only: Optional[List[str]] = None
    bypass_cooldown: bool = False


@router.get("/triggers", response_model=List[TriggerInfo])
async def list_registered_triggers(
    current_user: User = Depends(get_current_user),
) -> List[TriggerInfo]:
    """Names + cooldowns of every trigger registered at backend startup."""
    return [
        TriggerInfo(
            name=name,
            cooldown_seconds=trigger.cooldown_seconds,
            class_name=type(trigger).__name__,
        )
        for name, trigger in sorted(trigger_registry.items())
    ]


@router.post("/sweep")
async def run_sweep(
    body: SweepIn,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Run the trigger sweep on-demand. Mirrors the Celery beat task."""
    if body.only:
        unknown = [n for n in body.only if n not in trigger_registry]
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"unknown trigger(s): {unknown}"
            )

    async_session = get_async_session_factory()
    async with async_session() as db:
        results = await coordinator.sweep_all(
            db,
            user_id=str(current_user.id),
            bypass_cooldown=body.bypass_cooldown,
            only=body.only,
        )

    return {
        "checked": len(results),
        "emitted": sum(1 for r in results if r["status"] == "emitted"),
        "results": results,
    }


@router.post("/cooldowns/clear")
async def clear_cooldown(
    dedup_key: str = Query(..., description="Cooldown key to drop"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Drop a per-trigger Redis cooldown so the next sweep can re-fire."""
    await dispatch.clear_cooldown(dedup_key)
    return {"cleared": dedup_key}


def _row_to_out(row: Any) -> SystemEventOut:
    return SystemEventOut(
        id=str(row["id"]),
        user_id=row["user_id"],
        type=row["type"],
        title=row["title"],
        body=row["body"],
        subtitle=row["subtitle"],
        severity=row["severity"],
        trigger_name=row["trigger_name"],
        trigger_context=row["trigger_context"] or {},
        ttl_seconds=row["ttl_seconds"],
        sound=row["sound"],
        delivered_to=row["delivered_to"] or [],
        suppressed=row["suppressed"],
        suppression_reason=row["suppression_reason"],
        created_at=row["created_at"].isoformat(),
    )


# ── WebSocket stream ─────────────────────────────────────────────────────────


_NARRATION_CHANNEL = "sara:events:system.narration_emitted"


@router.websocket("/stream")
async def narrator_stream(websocket: WebSocket) -> None:
    """Live event stream for the webapp ticker.

    On connect: sends the most recent N events (initial load), then forwards
    every SYSTEM_NARRATION_EMITTED event as it lands on the bus.

    Auth via the JWT cookie set at login. WebSocket handshake doesn't have a
    convenient Depends pattern for cookies, so we do it manually here.
    """
    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=4001, reason="missing access_token cookie")
        return

    try:
        payload = verify_token(token)
        user_id = payload.get("sub") if payload else None
    except Exception:
        await websocket.close(code=4001, reason="invalid token")
        return
    if not user_id:
        await websocket.close(code=4001, reason="invalid token payload")
        return

    await websocket.accept()
    logger.info("narrator: WS connected for user %s", user_id)

    # Initial load — send recent history.
    try:
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(
                text(
                    """
                    SELECT id, user_id, type, title, body, subtitle, severity,
                           trigger_name, trigger_context, ttl_seconds, sound,
                           delivered_to, suppressed, suppression_reason, created_at
                    FROM system_event
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT 50
                    """
                ),
                {"user_id": user_id},
            )
            rows = list(result.mappings().all())
        await websocket.send_json({
            "type": "initial_load",
            "events": [_row_to_out(r).dict() for r in rows],
        })
    except Exception as exc:
        logger.exception("narrator: initial-load failed: %s", exc)

    # Subscribe to the bus channel and forward.
    import redis.asyncio as redis  # local import to avoid module-level cost

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    client = await redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(_NARRATION_CHANNEL)

    try:
        # listen() yields messages; the first one is the subscribe ack.
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                envelope = json.loads(msg["data"])
            except (json.JSONDecodeError, KeyError):
                continue
            # Filter to this user. Multi-user installs would otherwise
            # leak other users' events to whoever is connected.
            if envelope.get("user_id") != user_id:
                continue
            payload = envelope.get("payload") or {}
            try:
                await websocket.send_json({"type": "event", "event": payload})
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.warning("narrator: WS send failed: %s", exc)
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("narrator: WS stream error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe(_NARRATION_CHANNEL)
            await pubsub.close()
            await client.close()
        except Exception:
            pass
        logger.info("narrator: WS disconnected for user %s", user_id)


# ── Scheduled broadcast admin (PR 7) ─────────────────────────────────────────


_SCHEDULED_KINDS = (
    "daily_patch_notes",
    "weekly_recap",
    "sponsored_interjection",
)


@router.post("/scheduled/{kind}/run")
async def run_scheduled_broadcast(
    kind: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Trigger a scheduled broadcast on-demand. Mirrors the Celery task path."""
    if kind not in _SCHEDULED_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown scheduled kind; must be one of {list(_SCHEDULED_KINDS)}",
        )
    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await narrator_scheduled.run_scheduled(
            kind, str(current_user.id), db
        )
    return result
