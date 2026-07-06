"""Presence logging routes."""

import json
import logging
import os
import uuid
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
import redis

from app.db.session import get_db
from app.core.deps import get_current_user
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Presence"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# --- Redis-backed client state helpers ---

_CLIENT_STATE_PREFIX = "sara:client_state"
_CLIENT_STATE_TTL = 60  # seconds


def _client_key(user_id: str, client_id: str) -> str:
    return f"{_CLIENT_STATE_PREFIX}:{user_id}:{client_id}"


def get_active_clients(user_id: str) -> List[dict]:
    """Return all active client states for a user (keys with unexpired TTL)."""
    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        pattern = f"{_CLIENT_STATE_PREFIX}:{user_id}:*"
        clients = []
        for key in r.scan_iter(match=pattern, count=50):
            raw = r.get(key)
            if raw:
                clients.append(json.loads(raw))
        r.close()
        return clients
    except Exception as e:
        logger.error(f"Failed to get active clients: {e}")
        return []


def is_user_in_chat(user_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check whether any active client for this user is on the chat view.
    Returns (in_chat, platform) — platform of the first client in chat, or None.
    """
    for client in get_active_clients(user_id):
        view = client.get("current_view", "")
        if view in ("chat", "sara", "Sara"):
            return True, client.get("platform")
    return False, None


# --- Legacy presence log ---

async def log_presence(user_id: str, activity_type: str, platform: str = None, db: Session = None):
    """
    Log a presence/activity event for the user.
    Called from various endpoints to track when the user is active.
    """
    try:
        if db is None:
            from app.db.session import SessionLocal
            db = SessionLocal()
            close_db = True
        else:
            close_db = False

        try:
            db.execute(text("""
                INSERT INTO presence_log (id, user_id, activity_type, platform, created_at)
                VALUES (:id, :user_id, :activity_type, :platform, NOW())
            """), {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "activity_type": activity_type,
                "platform": platform
            })
            db.commit()
            logger.debug(f"Logged presence: {user_id} - {activity_type} ({platform})")
        finally:
            if close_db:
                db.close()

    except Exception as e:
        logger.error(f"Error logging presence: {e}")


@router.post("/api/presence")
async def log_presence_endpoint(
    data: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Log user presence/activity. Call this when app opens, resumes, or on significant actions.
    """
    activity_type = data.get("activity_type", "app_open")
    platform = data.get("platform", "unknown")

    await log_presence(current_user.id, activity_type, platform, db)

    return {"success": True, "message": "Presence logged"}


@router.post("/api/presence/heartbeat")
async def presence_heartbeat(
    data: dict,
    current_user=Depends(get_current_user)
):
    """
    Periodic heartbeat from web/iOS clients.

    Accepts:
      platform:     "web" | "ios"
      client_id:    stable per-session identifier
      current_view: "chat" | "notes" | "dashboard" | "fitness" | ...
      visible:      true if the app/tab is in the foreground
    """
    client_id = data.get("client_id", "unknown")
    state = {
        "platform": data.get("platform", "unknown"),
        "client_id": client_id,
        "current_view": data.get("current_view", "unknown"),
        "visible": data.get("visible", True),
        "user_id": current_user.id,
    }

    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        key = _client_key(current_user.id, client_id)
        r.setex(key, _CLIENT_STATE_TTL, json.dumps(state))
        r.close()
    except Exception as e:
        logger.error(f"Failed to store heartbeat: {e}")

    return {"ok": True}


@router.post("/desktop-activity")
async def report_desktop_activity(
    data: Dict,
    current_user=Depends(get_current_user),
):
    """
    Report desktop active window for activity state inference.

    Expected payload:
        app: str        — active app name (e.g. "VSCode", "Zoom")
        window_title: str — window title (optional)
        idle_seconds: int — seconds since last input (optional)
    """
    app = data.get("app", "")
    window_title = data.get("window_title", "")
    idle_seconds = data.get("idle_seconds", 0)

    # Feed into activity state machine
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivitySignal
        activity_state_machine.process_signal(ActivitySignal(
            signal_type="desktop",
            source="desktop_agent",
            value=app,
            metadata={
                "window_title": window_title,
                "idle_seconds": idle_seconds,
            },
        ))
    except Exception as e:
        logger.warning(f"Desktop activity signal failed: {e}")

    # Store in unified context
    try:
        from app.services.context_writer import update_fields
        import asyncio
        asyncio.ensure_future(update_fields(str(current_user.id), source="desktop_agent", **{
            "desktop_active_app": app,
            "desktop_active_window": window_title[:100] if window_title else "",
            "desktop_idle_seconds": idle_seconds,
        }))
    except Exception:
        pass

    return {"ok": True}


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    label: Optional[str] = None  # iOS may provide a label


@router.post("/location")
async def report_location(
    data: LocationUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Legacy significant-location-change endpoint. New iOS builds should use
    POST /api/location/report instead — kept here so old app builds keep working.
    """
    from app.services.location_service import process_report
    result = await process_report(db, current_user.id, data.latitude, data.longitude, data.accuracy, "ios_significant")
    return {"ok": True, "classified_place": result.get("classified_place") or data.label or "unknown"}
