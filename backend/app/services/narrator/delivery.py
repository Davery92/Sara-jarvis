"""Narrator delivery — fan out a SystemEvent to live surfaces.

Two surfaces wired:
- Desktop: any device with an active WebSocket on /api/devices/ws/{device_id}
  receives a CommandType.SYSTEM_EVENT command (PR 3).
- Mobile push: routed through unified_notification.send_notification so it
  inherits dedup, cooldowns, ban-phrase filtering, and the attention queue
  (PR 4). Per-severity category names (e.g. `narrator_roast`,
  `narrator_observation`) let each severity have its own cooldown knob.

The webapp ticker (PR 6) doesn't need a push — it subscribes to
SYSTEM_NARRATION_EMITTED on the event bus directly.

Suppressed events (`payload.suppressed == True`, the "noted, not narrated"
case) are persisted and emitted on the bus, but never delivered to a
surface. That is the whole point of suppression.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.command_router import (
    CommandMessage,
    CommandType,
    command_router,
)
from app.services.narrator.bus import SystemEventPayload
from app.services.unified_notification import send_notification


# severity → (cooldown category, push priority).
#
# The narrator is its own broadcast channel — not part of Sara's inbox /
# attention queue — so we always bypass attention routing in send_notification
# (see _bypass_attention=True below). Without that, low/normal priorities get
# silently queued instead of pushed, and the persona's punchiness vanishes on
# mobile.
#
# Priority drives whether the push interrupts (high) or arrives quietly (low).
SEVERITY_PUSH_MAP: Dict[str, Dict[str, str]] = {
    "roast":       {"category": "narrator_roast",       "priority": "high"},
    "achievement": {"category": "narrator_achievement", "priority": "high"},
    "observation": {"category": "narrator_observation", "priority": "low"},
    "patch_note":  {"category": "narrator_patch_note",  "priority": "high"},
    "sponsored":   {"category": "narrator_sponsored",   "priority": "low"},
    "grudging":    {"category": "narrator_grudging",    "priority": "normal"},
    "deflected":   {"category": "narrator_deflected",   "priority": "normal"},
}

logger = logging.getLogger(__name__)


async def dispatch(
    payload: SystemEventPayload,
    db: AsyncSession,
) -> List[str]:
    """Send the event to every connected desktop for `payload.user_id`.

    Returns the list of surface names that received it (currently just
    `"desktop:<device_id>"` entries). Also updates the row's `delivered_to`
    column so the ticker and audit endpoints reflect reality.
    """
    if payload.suppressed:
        logger.debug(
            "narrator: skipping delivery for suppressed event %s",
            payload.id,
        )
        return []

    # command_router holds an in-process registry of live WebSocket
    # connections — no DB needed.
    device_ids = list(command_router.get_connected_devices(payload.user_id))
    delivered: List[str] = []

    if device_ids:
        event_dict = payload.to_dict()
        for device_id in device_ids:
            command = CommandMessage(
                command_type=CommandType.SYSTEM_EVENT,
                payload=event_dict,
                target_device_id=device_id,
            )
            # send_command only reads `db` when target_device_id is None.
            sent = await command_router.send_command(
                db=None, user_id=payload.user_id, command=command
            )
            if sent:
                delivered.append(f"desktop:{device_id}")
    else:
        logger.info(
            "narrator: no connected desktops for user %s; event %s "
            "will reach mobile via push and the ticker",
            payload.user_id,
            payload.id,
        )

    # iOS / push surface — happens regardless of desktop status. Desktop
    # popups are best-effort real-time; push is the durable surface.
    push_label = await _deliver_push(payload, db)
    if push_label:
        delivered.append(push_label)

    if delivered and payload.id is not None:
        await _record_delivery(db, payload, delivered)

    return delivered


async def _deliver_push(
    payload: SystemEventPayload,
    db: AsyncSession,
) -> str | None:
    """Send the event as a push notification via unified_notification.

    Returns the delivered_to label (e.g. `"push:narrator_roast"`) on success,
    or None if the pipeline declined to send (cooldown, ban-phrase, no tokens).
    """
    mapping = SEVERITY_PUSH_MAP.get(payload.severity)
    if mapping is None:
        logger.warning(
            "narrator: no push mapping for severity %r; skipping push",
            payload.severity,
        )
        return None

    category = mapping["category"]
    priority = mapping["priority"]

    # tap-to-context: iOS handler reads these to populate the overlay modal.
    # title and body are duplicated explicitly here (the push pipeline already
    # sets data.message=body, but the iOS handler's primary lookups are for
    # data.body / data.title — providing both shapes avoids name mismatches).
    extra_push_data: Dict[str, Any] = {
        "type": "system_event",
        "event_id": str(payload.id) if payload.id else None,
        "title": payload.title,
        "body": payload.body,
        "severity": payload.severity,
        "trigger_name": payload.trigger_name,
        "subtitle": payload.subtitle,
        # iOS interruption hint. Observations slip into the notification
        # center quietly; everything else interrupts normally.
        "interruption_level": (
            "passive" if payload.severity in ("observation", "sponsored")
            else "active"
        ),
    }

    # Title prefix lifts the System AI persona out of the OS chrome so the
    # banner reads as a broadcast, not a Sara message.
    title_prefix = {
        "roast":       "📢 ",
        "achievement": "🏆 ",
        "observation": "👁 ",
        "patch_note":  "📋 ",
        "sponsored":   "📺 ",
        "grudging":    "🪙 ",
        "deflected":   "✦ ",
    }.get(payload.severity, "")

    push_title = f"{title_prefix}{payload.title}".strip()

    # Topic = event id so identical events can't double-push; the dedup
    # layer in unified_notification rejects same-topic firings.
    topic = f"narrator:{payload.id}" if payload.id else None

    try:
        result = await send_notification(
            user_id=payload.user_id,
            title=push_title,
            message=payload.body,
            priority=priority,
            topic=topic,
            category=category,
            source="narrator",
            db=db,
            extra_push_data=extra_push_data,
            # The narrator is its own broadcast channel. Don't let the
            # attention queue swallow low/normal severities, and don't let
            # the unified push pipeline send a duplicate SHOW_NOTIFICATION
            # to the desktop on top of our styled SYSTEM_EVENT popup.
            _bypass_attention=True,
            _bypass_desktop=True,
        )
    except Exception as exc:
        logger.warning("narrator: push send failed: %s", exc)
        return None

    if result.get("sent"):
        return f"push:{category}"
    logger.info(
        "narrator: push declined by pipeline (reason=%s) for event %s",
        result.get("reason"),
        payload.id,
    )
    return None


async def _record_delivery(
    db: AsyncSession,
    payload: SystemEventPayload,
    delivered: List[str],
) -> None:
    """Persist the delivery fanout to system_event.delivered_to.

    Merges with whatever was already there (in case a future code path
    records, say, an iOS delivery before this one runs). Failures here are
    logged but never raised — the event was already sent to the user, the
    audit trail just gets less precise.
    """
    import json

    try:
        # JSONB || JSONB does element-wise concatenation on arrays; we wrap
        # with COALESCE in case delivered_to was somehow NULL.
        await db.execute(
            text(
                """
                UPDATE system_event
                SET delivered_to = COALESCE(delivered_to, '[]'::jsonb)
                    || CAST(:new_entries AS jsonb)
                WHERE id = :id
                """
            ),
            {"id": str(payload.id), "new_entries": json.dumps(delivered)},
        )
        await db.commit()
        payload.delivered_to = list(payload.delivered_to) + delivered
    except Exception as exc:
        logger.warning(
            "narrator: failed to record delivery for %s: %s",
            payload.id,
            exc,
        )
