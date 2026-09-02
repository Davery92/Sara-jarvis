"""Mirror still-active legacy EventBus senses into the durable world ledger."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.services.world_state.writer import append_world_event_async

logger = logging.getLogger(__name__)

# These domains already append in the same database transaction at their
# authoritative write sites. Mirroring them here would only create duplicates.
_DIRECT_PREFIXES = ("workout.", "food.", "note.", "calendar_event.", "agent_task.")
_DIRECT_KINDS = {"chat.message_received"}

_KIND_MAP = {
    "health.data_synced": "health.sync_completed",
    "health.sleep_imported": "sleep.imported",
    "location.place_entered": "location.entered",
    "location.place_exited": "location.exited",
    "presence.room_changed": "presence.changed",
    "presence.device_active_changed": "presence.changed",
    "activity.state_changed": "presence.changed",
    "prediction.violated": "expectation.violated",
}


def _aggregate(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "id", "event_id", "task_id", "goal_id", "reminder_id", "timer_id",
        "session_id", "entity_id", "place_id", "device_id", "thread_id",
    ):
        if payload.get(key) is not None:
            return str(payload[key])
    return None


async def record_legacy_event(event: Any) -> Dict[str, str]:
    legacy_kind = str(getattr(event.event_type, "value", event.event_type))
    if legacy_kind in _DIRECT_KINDS or legacy_kind.startswith(_DIRECT_PREFIXES):
        return {"effect": "authoritative_writer"}

    from app.db.session import get_async_session_factory

    payload = dict(event.payload or {})
    kind = _KIND_MAP.get(legacy_kind, legacy_kind)
    aggregate_id = _aggregate(payload)
    factory = get_async_session_factory()
    async with factory() as db:
        row = await append_world_event_async(
            db,
            user_id=str(event.user_id),
            kind=kind,
            source=f"legacy_event_bus:{event.source}",
            source_ref=str(payload.get("source_ref") or aggregate_id or event.event_id),
            aggregate_type=kind.split(".", 1)[0],
            aggregate_id=aggregate_id,
            actor_type="system",
            dedupe_key=f"legacy-event-bus:{event.event_id}",
            payload={**payload, "legacy_kind": legacy_kind, "metadata": dict(event.metadata or {})},
            occurred_at=event.timestamp,
            observed_at=event.timestamp,
            provenance={"bridge": "legacy_event_bus_v1"},
        )
        await db.commit()
    return {"effect": "recorded", "event_id": row.event_id if row else "disabled"}
