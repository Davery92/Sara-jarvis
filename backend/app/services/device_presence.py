"""Unified device presence resolver (Desktop Jarvis Overhaul A7).

Answers one question the same way everywhere: "which device is David active
on right now, and where is he." Combines signals that today are each read
separately by different callers:
  - Desktop heartbeats (machine_registry / device_orchestrator profiles)
  - iOS/web foreground presence (routes/presence.py's Redis client states)
  - Jetson desk presence + online state (unified_context snapshot)
  - Location (unified_context snapshot's current_place_type)

Debounces DEVICE_ACTIVE_CHANGED so a flickering signal doesn't spam the
event bus — the resolved answer only "changes" (and publishes) after it's
been different for >= DEBOUNCE_SECONDS, and the snapshot itself is cached
in Redis so repeated callers within a few seconds don't re-run the whole
resolution.
"""
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_KEY = "sara:device_presence:{user_id}"
CACHE_TTL_SECONDS = 30
DEBOUNCE_SECONDS = 60


@dataclass
class DevicePresence:
    active_device_id: Optional[str]
    active_device_name: Optional[str]
    platform: Optional[str]
    activity_level: Optional[str]
    location_context: str  # "home" | "work" | "away" | "unknown"
    confidence: float
    since: str  # ISO timestamp of when this answer was last (re)computed


async def _get_redis():
    return aioredis.from_url(REDIS_URL, decode_responses=True)


async def _resolve_uncached(db, user_id: str) -> DevicePresence:
    from app.services.device_orchestrator import device_orchestrator
    from app.services.unified_context import read_snapshot
    from app.routes.presence import is_user_in_chat, get_active_clients

    now = datetime.now(timezone.utc).isoformat()
    snapshot = await read_snapshot(user_id)
    location_context = snapshot.current_place_type or "unknown"
    if location_context not in ("home", "work"):
        location_context = "away" if snapshot.current_place and snapshot.current_place != "unknown" else "unknown"

    profiles = await device_orchestrator.get_device_profiles(db, user_id)

    # 1. A desktop actively being used beats everything — it's the richest
    #    surface and the strongest "David is right here" signal.
    active_desktops = [
        p for p in profiles
        if p.device_class.value == "desktop" and p.is_active
    ]
    if active_desktops:
        best = max(active_desktops, key=lambda p: p.last_activity_at or datetime.min.replace(tzinfo=None))
        return DevicePresence(
            active_device_id=best.device_id,
            active_device_name=best.friendly_name,
            platform=best.platform,
            activity_level=best.activity_level,
            location_context=location_context,
            confidence=0.9,
            since=now,
        )

    # 2. Phone/web foreground in the chat view — David is looking at Sara
    #    on this device right now.
    in_chat, chat_platform = is_user_in_chat(user_id)
    if in_chat:
        return DevicePresence(
            active_device_id=None,
            active_device_name=chat_platform or "phone",
            platform=chat_platform,
            activity_level="high",
            location_context=location_context,
            confidence=0.75,
            since=now,
        )

    # 3. Jetson desk presence — face-detected at the desk and the Jetson is
    #    actually online (not a stale flag).
    if snapshot.desk_presence and snapshot.jetson_online:
        return DevicePresence(
            active_device_id="jetson",
            active_device_name="Jetson (desk)",
            platform="jetson",
            activity_level="medium",
            location_context=location_context,
            confidence=0.6,
            since=now,
        )

    # 4. Any online desktop, even if idle — better than nothing for routing.
    online_desktops = [p for p in profiles if p.device_class.value == "desktop" and p.is_online]
    if online_desktops:
        best = online_desktops[0]
        return DevicePresence(
            active_device_id=best.device_id,
            active_device_name=best.friendly_name,
            platform=best.platform,
            activity_level=best.activity_level,
            location_context=location_context,
            confidence=0.3,
            since=now,
        )

    # 5. Any connected client at all (web/iOS heartbeat present, but not on
    #    the chat view specifically).
    clients = get_active_clients(user_id)
    if clients:
        c = clients[0]
        return DevicePresence(
            active_device_id=None,
            active_device_name=c.get("platform") or "phone",
            platform=c.get("platform"),
            activity_level="low",
            location_context=location_context,
            confidence=0.2,
            since=now,
        )

    return DevicePresence(
        active_device_id=None,
        active_device_name=None,
        platform=None,
        activity_level=None,
        location_context=location_context,
        confidence=0.0,
        since=now,
    )


async def resolve(db, user_id: str, force: bool = False) -> DevicePresence:
    """Resolve current device presence, using a short Redis cache to avoid
    re-running the full multi-source resolution on every call (chat context
    assembly, overlay routing, and voice-note device selection all call
    this within the same turn)."""
    r = await _get_redis()
    key = CACHE_KEY.format(user_id=user_id)
    try:
        if not force:
            cached = await r.get(key)
            if cached:
                return DevicePresence(**json.loads(cached))

        result = await _resolve_uncached(db, user_id)
        await _publish_if_changed(r, user_id, result)
        await r.setex(key, CACHE_TTL_SECONDS, json.dumps(asdict(result)))
        return result
    finally:
        await r.close()


async def _publish_if_changed(r, user_id: str, result: DevicePresence) -> None:
    """Debounced DEVICE_ACTIVE_CHANGED — only fires when the resolved active
    device differs from last time AND it's been >= DEBOUNCE_SECONDS since
    the last change, so a flapping signal doesn't spam the event bus."""
    last_key = f"sara:device_presence:last_active:{user_id}"
    last_changed_key = f"sara:device_presence:last_changed_at:{user_id}"

    last_active = await r.get(last_key)
    current_active = result.active_device_id or result.active_device_name or ""

    if last_active == current_active:
        return

    last_changed_raw = await r.get(last_changed_key)
    now = datetime.now(timezone.utc)
    if last_changed_raw:
        try:
            last_changed = datetime.fromisoformat(last_changed_raw)
            if (now - last_changed).total_seconds() < DEBOUNCE_SECONDS:
                return
        except ValueError:
            pass

    await r.set(last_key, current_active)
    await r.set(last_changed_key, now.isoformat())

    try:
        from app.services.event_bus import event_bus, Event, EventType
        await event_bus.publish(Event(
            event_type=EventType.DEVICE_ACTIVE_CHANGED,
            user_id=user_id,
            source="device_presence",
            payload=asdict(result),
        ))
    except Exception as e:
        logger.warning(f"Failed to publish DEVICE_ACTIVE_CHANGED: {e}")


def format_context_line(presence: DevicePresence) -> Optional[str]:
    """One line for chat/voice system-prompt injection (A7)."""
    if not presence.active_device_name:
        return f"David's location: {presence.location_context}."
    if presence.platform and presence.activity_level:
        return (
            f"David is currently active on {presence.active_device_name} "
            f"({presence.platform}, {presence.activity_level}); location: {presence.location_context}."
        )
    return f"David is currently active on {presence.active_device_name}; location: {presence.location_context}."
