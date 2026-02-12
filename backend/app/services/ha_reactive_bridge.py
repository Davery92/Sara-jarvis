"""
Home Assistant Reactive Bridge

Bridges HA websocket state_changed events into the Redis event bus,
enabling real-time reactive handlers instead of polling.

This module is imported by the HA websocket service and called on each
state change. It:
1. Publishes typed events to the Redis event bus
2. Feeds signals into the activity state machine
3. Detects anomalies (unusual activity patterns)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")
DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"

# Anomaly: door/motion events during these hours are noteworthy
QUIET_HOURS = (23, 5)  # 11 PM to 5 AM

# Track recent events for anomaly detection (in-memory)
_recent_events: list = []
_MAX_RECENT = 200


def _is_quiet_hours(now: datetime) -> bool:
    h = now.hour
    start, end = QUIET_HOURS
    if start > end:
        return h >= start or h < end
    return start <= h < end


def _classify_ha_event(
    entity_id: str,
    domain: str,
    from_state: Optional[str],
    to_state: str,
    attributes: Dict[str, Any],
    changed_at: datetime,
) -> Dict[str, Any]:
    """
    Classify an HA state change into a typed event for the event bus.

    Returns a dict with:
      event_type: EventType string value
      payload: event-specific data
      activity_signal: signal dict for the activity state machine (or None)
      anomaly: anomaly description (or None)
    """
    result = {
        "event_type": "home.state_changed",
        "payload": {
            "entity_id": entity_id,
            "domain": domain,
            "from_state": from_state,
            "to_state": to_state,
            "friendly_name": attributes.get("friendly_name", entity_id),
            "changed_at": changed_at.isoformat(),
        },
        "activity_signal": None,
        "anomaly": None,
    }

    name = entity_id.lower()
    friendly = attributes.get("friendly_name", "").lower()

    # --- Motion / occupancy sensors ---
    if domain == "binary_sensor" and any(
        kw in name for kw in ["motion", "occupancy", "presence"]
    ):
        result["event_type"] = "home.motion_detected"
        room = _extract_room(entity_id)
        result["payload"]["room"] = room
        result["payload"]["detected"] = to_state == "on"

        if to_state == "on":
            result["activity_signal"] = {
                "signal_type": "motion",
                "source": entity_id,
                "value": "on",
                "metadata": {"room": room},
            }

            # Anomaly: motion during quiet hours
            if _is_quiet_hours(changed_at):
                result["anomaly"] = f"Motion detected in {room or entity_id} during quiet hours ({changed_at.strftime('%H:%M')})"

    # --- Door / window sensors ---
    elif domain == "binary_sensor" and any(
        kw in name for kw in ["door", "window", "contact", "entry"]
    ):
        result["event_type"] = "home.door_changed"
        opened = to_state == "on"  # binary_sensor: on = open for contact sensors
        result["payload"]["opened"] = opened
        result["payload"]["location"] = _extract_room(entity_id) or friendly

        if opened and _is_quiet_hours(changed_at):
            result["anomaly"] = f"Door/window opened: {friendly or entity_id} at {changed_at.strftime('%H:%M')} (quiet hours)"

    # --- Lights ---
    elif domain == "light":
        result["event_type"] = "home.light_changed"
        result["payload"]["brightness"] = attributes.get("brightness")
        result["payload"]["room"] = _extract_room(entity_id)

    # --- Climate (skip unavailable — removed devices) ---
    elif domain == "climate" and to_state not in ("unavailable", "unknown"):
        result["event_type"] = "home.climate_changed"
        result["payload"]["temperature"] = attributes.get("temperature")
        result["payload"]["current_temperature"] = attributes.get("current_temperature")
        result["payload"]["hvac_mode"] = to_state

    # --- Lock ---
    elif domain == "lock":
        result["payload"]["locked"] = to_state == "locked"
        if to_state == "unlocked" and _is_quiet_hours(changed_at):
            result["anomaly"] = f"Lock unlocked: {friendly or entity_id} at {changed_at.strftime('%H:%M')} (quiet hours)"

    # --- Media player ---
    elif domain == "media_player":
        result["payload"]["media_state"] = to_state
        if to_state == "playing":
            result["activity_signal"] = {
                "signal_type": "media",
                "source": entity_id,
                "value": "playing",
                "metadata": {
                    "room": _extract_room(entity_id),
                    "media_title": attributes.get("media_title"),
                },
            }

    return result


async def bridge_ha_event(
    entity_id: str,
    domain: str,
    from_state: Optional[str],
    to_state: str,
    attributes: Dict[str, Any],
    changed_at: datetime,
):
    """
    Called by the HA websocket service on each state change.
    Publishes to Redis event bus and feeds activity state machine.
    """
    classified = _classify_ha_event(
        entity_id, domain, from_state, to_state, attributes, changed_at
    )

    # Track for anomaly detection
    _recent_events.append({
        "entity_id": entity_id,
        "to_state": to_state,
        "at": changed_at,
    })
    if len(_recent_events) > _MAX_RECENT:
        _recent_events.pop(0)

    # 1. Publish to event bus
    try:
        from app.services.event_bus import event_bus, EventType, Event

        event_type_str = classified["event_type"]
        # Map string to EventType enum
        event_type_map = {
            "home.state_changed": EventType.HOME_STATE_CHANGED,
            "home.motion_detected": EventType.HOME_MOTION_DETECTED,
            "home.door_changed": EventType.HOME_DOOR_CHANGED,
            "home.light_changed": EventType.HOME_LIGHT_CHANGED,
            "home.climate_changed": EventType.HOME_CLIMATE_CHANGED,
        }
        evt_type = event_type_map.get(event_type_str, EventType.HOME_STATE_CHANGED)

        event = Event(
            event_type=evt_type,
            user_id=DAVID_USER_ID,
            payload=classified["payload"],
            source="ha_bridge",
        )
        await event_bus.publish(event)

    except Exception as e:
        logger.debug(f"Event bus publish failed (may not be connected): {e}")

    # 2. Feed activity state machine
    if classified["activity_signal"]:
        try:
            from app.services.activity_state_machine import (
                activity_state_machine,
                ActivitySignal,
            )

            sig = classified["activity_signal"]
            activity_state_machine.process_signal(
                ActivitySignal(
                    signal_type=sig["signal_type"],
                    source=sig["source"],
                    value=sig["value"],
                    timestamp=changed_at if changed_at.tzinfo else changed_at.replace(tzinfo=USER_TZ),
                    metadata=sig.get("metadata", {}),
                )
            )

            # Publish any activity state transitions to the event bus
            state_events = activity_state_machine.drain_pending_events()
            for se in state_events:
                try:
                    await event_bus.publish(Event(
                        event_type=EventType.ACTIVITY_STATE_CHANGED,
                        user_id=DAVID_USER_ID,
                        payload=se,
                        source="activity_state_machine",
                    ))
                except Exception as pub_err:
                    logger.debug(f"Failed to publish activity state change: {pub_err}")

        except Exception as e:
            logger.debug(f"Activity state machine signal failed: {e}")

    # 3. Write environment updates to unified context snapshot
    try:
        from app.services.context_writer import update_fields
        payload = classified["payload"]
        context_updates = {}

        if classified["event_type"] == "home.motion_detected":
            room = payload.get("room")
            if room and payload.get("detected"):
                context_updates["room"] = room
                context_updates["home_occupied"] = True

        elif classified["event_type"] == "home.climate_changed":
            temp = payload.get("current_temperature")
            if temp is not None:
                context_updates["temperature_inside"] = float(temp)

        if context_updates:
            await update_fields(DAVID_USER_ID, source="ha_bridge", **context_updates)
    except Exception as e:
        logger.debug(f"Context snapshot update failed (non-critical): {e}")

    # 4. Handle anomalies
    if classified["anomaly"]:
        logger.warning(f"HA anomaly: {classified['anomaly']}")
        try:
            from app.services.event_bus import event_bus, EventType, Event

            anomaly_event = Event(
                event_type=EventType.HOME_ANOMALY_DETECTED,
                user_id=DAVID_USER_ID,
                payload={
                    "description": classified["anomaly"],
                    "entity_id": entity_id,
                    "to_state": to_state,
                    "changed_at": changed_at.isoformat(),
                },
                source="ha_bridge",
            )
            await event_bus.publish(anomaly_event)
        except Exception as e:
            logger.debug(f"Anomaly event publish failed: {e}")


def _extract_room(entity_id: str) -> Optional[str]:
    """Extract room name from HA entity ID."""
    parts = entity_id.split(".", 1)
    if len(parts) < 2:
        return None

    name = parts[1].lower()
    room_keywords = [
        "office", "kitchen", "bedroom", "bathroom", "living_room",
        "living", "garage", "basement", "attic", "hallway",
        "dining", "den", "studio", "gym", "laundry",
        "front_door", "back_door", "porch", "patio",
    ]

    for room in room_keywords:
        if room in name:
            return room

    for suffix in ["_motion", "_occupancy", "_presence", "_sensor",
                    "_lamp", "_light", "_door", "_window", "_contact"]:
        if suffix in name:
            candidate = name.split(suffix)[0].replace("_", " ").strip()
            if candidate:
                return candidate

    return None
