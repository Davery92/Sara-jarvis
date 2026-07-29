"""Subconscious endpoints — state, nudges, and the SSE stream.

Extracted from main_simple.py. Routes stay cookie-auth only (Pi-facing
variants live in routes/pi_dashboard.py).

SSE cap (audit fix): ``nudge_stream`` used to poll every 10s forever with
no lifetime cap. A long-lived browser tab would hold the DB dependency
and eventually starve the pool. We now cap the stream at
``SSE_MAX_LIFETIME_SECONDS`` (default 1 hour) and rely on the client to
reconnect — SSE clients do this automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main_simple import get_current_user  # noqa: E402 — sync dep from god-file

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard cap on a single SSE connection. Browser EventSource reconnects
# automatically so capping here doesn't break the UX — it just prevents
# a single tab from holding a DB session forever.
SSE_MAX_LIFETIME_SECONDS = int(os.getenv("NUDGE_STREAM_MAX_SECONDS", "3600"))
SSE_POLL_SECONDS = int(os.getenv("NUDGE_STREAM_POLL_SECONDS", "10"))


@router.get("/api/subconscious/state")
async def get_subconscious_state(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return Sara's current mental-model snapshot for context injection."""
    try:
        user_id = current_user.id
        result = db.execute(
            text("SELECT * FROM subconscious_state WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).fetchone()

        if not result:
            return {"message": "No state available yet", "user_id": user_id}

        state = dict(result._mapping)
        # Arc 0.8: last_meal_type/last_meal_at/hours_since_meal/typical_meal_windows
        # have no writer anywhere in the codebase — the column was stuck at a
        # one-time seed (2026-02-17) while /api/sara/status computed a live,
        # correct hours-since-meal from the food log, so the two surfaces
        # disagreed. Dropping the dead fields here rather than reviving a
        # writer for a store Arc 2's world_state replaces outright.
        for dead_field in ("last_meal_type", "last_meal_at", "hours_since_meal", "typical_meal_windows"):
            state.pop(dead_field, None)
        json_fields = (
            "current_focus_areas",
            "active_threads",
            "docker_health",
            "service_health",
        )
        for field in json_fields:
            if state.get(field) and isinstance(state[field], str):
                try:
                    state[field] = json.loads(state[field])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse JSON field {field}: {e}")
        ts_fields = ("last_presence_at", "updated_at", "created_at")
        for field in ts_fields:
            if state.get(field):
                state[field] = (
                    state[field].isoformat()
                    if hasattr(state[field], "isoformat")
                    else str(state[field])
                )
        return state
    except Exception as e:
        logger.error(f"Error getting subconscious state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/subconscious/nudges")
async def get_subconscious_nudges(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List pending nudges, urgent-first."""
    try:
        user_id = current_user.id
        result = db.execute(
            text(
                """
                SELECT id, nudge_type, severity, title, message, action_suggestion,
                       delivery_channel, created_at, expires_at
                FROM subconscious_nudge
                WHERE user_id = :user_id
                  AND status IN ('pending', 'delivered')
                  AND expires_at > NOW()
                ORDER BY
                    CASE severity
                        WHEN 'urgent' THEN 1
                        WHEN 'gentle' THEN 2
                        ELSE 3
                    END,
                    created_at DESC
                """
            ),
            {"user_id": user_id},
        ).fetchall()

        nudges = []
        for r in result:
            nudge = dict(r._mapping)
            nudge["created_at"] = (
                nudge["created_at"].isoformat() if nudge.get("created_at") else None
            )
            nudge["expires_at"] = (
                nudge["expires_at"].isoformat() if nudge.get("expires_at") else None
            )
            nudges.append(nudge)

        return nudges
    except Exception as e:
        logger.error(f"Error getting nudges: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/subconscious/nudges/{nudge_id}/acknowledge")
async def acknowledge_nudge(
    nudge_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark a nudge as acknowledged."""
    try:
        user_id = current_user.id
        result = db.execute(
            text(
                """
                UPDATE subconscious_nudge
                SET acknowledged_at = NOW(), status = 'acknowledged'
                WHERE id = :nudge_id
                  AND user_id = :user_id
                  AND status IN ('pending', 'delivered')
                """
            ),
            {"nudge_id": nudge_id, "user_id": user_id},
        )
        db.commit()

        if result.rowcount > 0:
            return {"success": True, "nudge_id": nudge_id}
        raise HTTPException(
            status_code=404, detail="Nudge not found or already acknowledged"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging nudge: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/subconscious/nudges/stream")
async def nudge_stream(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """SSE stream of new nudges.

    Polls every ``SSE_POLL_SECONDS`` seconds for up to
    ``SSE_MAX_LIFETIME_SECONDS`` seconds per connection, then closes so
    the client reconnects. The cap exists because the prior unbounded
    loop held a DB session for the lifetime of every open tab.
    """
    user_id = current_user.id

    async def generate_events() -> AsyncGenerator[str, None]:
        # Tz-aware so comparisons against TIMESTAMPTZ columns don't
        # silently cross a DST boundary. The old version used datetime.now()
        # which is naive.
        last_check = datetime.now(timezone.utc)
        deadline = asyncio.get_event_loop().time() + SSE_MAX_LIFETIME_SECONDS
        while True:
            if await request.is_disconnected():
                break
            if asyncio.get_event_loop().time() >= deadline:
                # Signal the client to reconnect cleanly.
                yield "event: bye\ndata: {\"reason\":\"max_lifetime\"}\n\n"
                break

            try:
                result = db.execute(
                    text(
                        """
                        SELECT id, nudge_type, severity, title, message,
                               action_suggestion, delivery_channel, created_at
                        FROM subconscious_nudge
                        WHERE user_id = :user_id
                          AND status IN ('pending', 'delivered')
                          AND created_at > :last_check
                          AND expires_at > NOW()
                        ORDER BY created_at DESC
                        """
                    ),
                    {"user_id": user_id, "last_check": last_check},
                ).fetchall()
            except Exception as e:
                logger.warning(f"nudge_stream poll failed: {e}")
                # Surface a heartbeat event rather than silently stalling.
                yield f"event: error\ndata: {json.dumps({'error': type(e).__name__})}\n\n"
                await asyncio.sleep(SSE_POLL_SECONDS)
                continue

            for r in result:
                nudge = dict(r._mapping)
                nudge["created_at"] = (
                    nudge["created_at"].isoformat()
                    if nudge.get("created_at")
                    else None
                )
                yield f"data: {json.dumps({'type': 'nudge', 'nudge': nudge})}\n\n"

            last_check = datetime.now(timezone.utc)
            await asyncio.sleep(SSE_POLL_SECONDS)

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disables proxy buffering
        },
    )
