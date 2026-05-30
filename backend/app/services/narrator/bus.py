"""Narrator bus — persist a SystemEvent row and publish it on EventBus.

PR 1 surface: just the write-and-publish primitive. No LLM, no triggers,
no surface delivery yet. That keeps the schema, the bus contract, and the
admin test endpoint independently verifiable before we wire in the
persona layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.event_bus import EventType, emit_event

logger = logging.getLogger(__name__)


Severity = Literal[
    "roast",
    "observation",
    "achievement",
    "patch_note",
    "sponsored",
    "grudging",
    "deflected",
]

VALID_SEVERITIES: tuple[Severity, ...] = (
    "roast",
    "observation",
    "achievement",
    "patch_note",
    "sponsored",
    "grudging",
    "deflected",
)


@dataclass
class SystemEventPayload:
    """In-flight representation of a narrator utterance.

    `id` and `created_at` are populated by `publish()` after the INSERT.
    """

    user_id: str
    type: str
    title: str
    body: str
    severity: Severity
    trigger_name: str
    trigger_context: Dict[str, Any] = field(default_factory=dict)
    subtitle: Optional[str] = None
    ttl_seconds: int = 30
    sound: Optional[str] = None
    delivered_to: List[str] = field(default_factory=list)
    suppressed: bool = False
    suppression_reason: Optional[str] = None

    id: Optional[UUID] = None
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id) if self.id else None,
            "user_id": self.user_id,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "subtitle": self.subtitle,
            "severity": self.severity,
            "trigger_name": self.trigger_name,
            "trigger_context": self.trigger_context,
            "ttl_seconds": self.ttl_seconds,
            "sound": self.sound,
            "delivered_to": self.delivered_to,
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


async def publish(
    payload: SystemEventPayload,
    db: AsyncSession,
) -> SystemEventPayload:
    """Persist a system event and emit it on the EventBus.

    Returns the same payload with `id` and `created_at` populated.

    Suppressed events are persisted (so the ticker's "noted, not narrated"
    panel has something to count) but still emitted on the bus — subscribers
    can decide whether to render them based on `payload.suppressed`.
    """
    if payload.severity not in VALID_SEVERITIES:
        raise ValueError(
            f"invalid severity {payload.severity!r}; "
            f"must be one of {VALID_SEVERITIES}"
        )

    row = (
        await db.execute(
            text(
                """
                INSERT INTO system_event (
                    user_id, type, title, body, subtitle, severity,
                    trigger_name, trigger_context, ttl_seconds, sound,
                    delivered_to, suppressed, suppression_reason
                ) VALUES (
                    :user_id, :type, :title, :body, :subtitle, :severity,
                    :trigger_name, CAST(:trigger_context AS jsonb),
                    :ttl_seconds, :sound,
                    CAST(:delivered_to AS jsonb), :suppressed, :suppression_reason
                )
                RETURNING id, created_at
                """
            ),
            {
                "user_id": payload.user_id,
                "type": payload.type,
                "title": payload.title,
                "body": payload.body,
                "subtitle": payload.subtitle,
                "severity": payload.severity,
                "trigger_name": payload.trigger_name,
                "trigger_context": _json(payload.trigger_context),
                "ttl_seconds": payload.ttl_seconds,
                "sound": payload.sound,
                "delivered_to": _json(payload.delivered_to),
                "suppressed": payload.suppressed,
                "suppression_reason": payload.suppression_reason,
            },
        )
    ).one()

    payload.id = row.id
    payload.created_at = row.created_at
    await db.commit()

    try:
        await emit_event(
            event_type=EventType.SYSTEM_NARRATION_EMITTED,
            user_id=payload.user_id,
            payload=payload.to_dict(),
            source="narrator",
        )
    except Exception as exc:
        # Don't let a bus hiccup roll back the durable row. Surfaces that
        # missed the live event will catch up via /api/narrator/events.
        logger.warning(f"narrator: bus emit failed (row persisted): {exc}")

    logger.info(
        f"narrator: emitted {payload.severity}/{payload.trigger_name} "
        f"id={payload.id} suppressed={payload.suppressed}"
    )
    return payload


def _json(value: Any) -> str:
    """Serialize Python value for a CAST(:param AS jsonb) bind."""
    import json

    return json.dumps(value, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")
