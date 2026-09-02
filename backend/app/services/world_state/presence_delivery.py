"""Deliver presence revisions to WidgetKit caches and ActivityKit."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import httpx
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.live_activity import LiveActivityRegistration
from app.models.push_token import PushToken
from app.models.world_model import SaraPresenceSnapshot, WorldEvent

logger = logging.getLogger(__name__)


def _private_key() -> Optional[str]:
    inline = os.getenv("APPLE_APNS_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if inline:
        return inline
    path = os.getenv("APPLE_APNS_PRIVATE_KEY_PATH", "").strip()
    if path and Path(path).is_file():
        return Path(path).read_text()
    return None


def _auth_token() -> Optional[str]:
    key_id = os.getenv("APPLE_APNS_KEY_ID", "").strip()
    team_id = os.getenv("APPLE_TEAM_ID", "7MAK5MEJ6W").strip()
    key = _private_key()
    if not key_id or not team_id or not key:
        return None
    return jwt.encode(
        {"iss": team_id, "iat": int(time.time())}, key,
        algorithm="ES256", headers={"kid": key_id},
    )


def _content_state(presence: SaraPresenceSnapshot) -> Dict[str, object]:
    return {
        "subtitle": presence.headline,
        "startEpochMs": 0,
        "state": presence.state,
        "detail": presence.detail or "",
        "revision": int(presence.revision or 0),
        "validUntilEpochMs": presence.valid_until.timestamp() * 1000,
    }


async def _send_activity(
    registration: LiveActivityRegistration, presence: SaraPresenceSnapshot,
    *, end: bool = False,
) -> bool:
    token = _auth_token()
    if not token:
        logger.debug("[presence-delivery] APNs credentials not configured")
        return False
    bundle_id = os.getenv("APPLE_BUNDLE_ID", "cloud.avery.sara-ios")
    production = registration.environment != "sandbox"
    host = "https://api.push.apple.com" if production else "https://api.sandbox.push.apple.com"
    now = int(time.time())
    aps: Dict[str, object] = {
        "timestamp": now,
        "event": "end" if end else "update",
        "content-state": _content_state(presence),
        "stale-date": int(presence.valid_until.timestamp()),
    }
    if end:
        aps["dismissal-date"] = now + 5
    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": f"{bundle_id}.push-type.liveactivity",
        "apns-push-type": "liveactivity",
        "apns-priority": "10",
    }
    try:
        async with httpx.AsyncClient(http2=True, timeout=12) as client:
            response = await client.post(
                f"{host}/3/device/{registration.push_token}",
                headers=headers, json={"aps": aps},
            )
        if response.status_code == 200:
            return True
        logger.warning("[presence-delivery] APNs %s for %s: %s", response.status_code, registration.activity_id, response.text[:300])
        return False
    except Exception as exc:
        logger.warning("[presence-delivery] APNs failed for %s: %s", registration.activity_id, exc)
        return False


async def _send_widget_wakes(db: Session, user_id: str, revision: int) -> int:
    rows = db.execute(select(PushToken).where(
        PushToken.user_id == user_id,
        PushToken.platform == "ios",
        PushToken.is_active.is_(True),
    )).scalars().all()
    if not rows:
        return 0
    messages = [{
        "to": row.token,
        "data": {"type": "world_presence_update", "revision": revision},
        "priority": "normal",
        "_contentAvailable": True,
    } for row in rows]
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                "https://exp.host/--/api/v2/push/send", json=messages,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            response.raise_for_status()
        return len(messages)
    except Exception as exc:
        logger.warning("[presence-delivery] widget wake failed: %s", exc)
        return 0


async def deliver(db: Session, user_id: str, *, event_id: Optional[str] = None) -> Dict[str, int]:
    presence = db.execute(select(SaraPresenceSnapshot).where(
        SaraPresenceSnapshot.user_id == str(user_id)
    )).scalar_one_or_none()
    if presence is None:
        return {"activities": 0, "ended": 0, "widget_wakes": 0}
    event = None
    if event_id:
        event = db.execute(select(WorldEvent).where(WorldEvent.event_id == event_id)).scalar_one_or_none()
    terminal = bool(event and event.kind in {"task.completed", "task.failed", "workout.completed", "workout.abandoned"})
    terminal_id = str(event.aggregate_id) if terminal and event and event.aggregate_id else None
    registrations = db.execute(select(LiveActivityRegistration).where(
        LiveActivityRegistration.user_id == str(user_id),
        LiveActivityRegistration.is_active.is_(True),
    )).scalars().all()
    sent = ended = 0
    for registration in registrations:
        should_end = bool(terminal_id and registration.logical_id == terminal_id)
        if await _send_activity(registration, presence, end=should_end):
            sent += 1
            if should_end:
                registration.is_active = False
                registration.ended_at = datetime.now(timezone.utc)
                ended += 1
    db.commit()
    wakes = await _send_widget_wakes(db, str(user_id), int(presence.revision or 0))
    return {"activities": sent, "ended": ended, "widget_wakes": wakes}
