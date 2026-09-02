"""Same-transaction world-event writers for sync and async SQLAlchemy sessions."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import event as sa_event, select
from sqlalchemy.orm import Session

from app.models.world_model import WorldEvent, WorldEventProcessing
from app.schemas.world_events import EventEnvelopeV2
from app.services.world_state.catalog import get_spec

logger = logging.getLogger(__name__)
_HOOK_INSTALLED = False
_EVENT_IDS_INFO_KEY = "world_event_ids_after_commit"


def _enabled() -> bool:
    return os.getenv("WORLD_EVENTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}



def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _dispatch_ids(session: Session) -> None:
    ids = list(session.info.pop(_EVENT_IDS_INFO_KEY, []))
    if not ids:
        return
    try:
        from app.celery_app import celery_app
        for event_id in ids:
            celery_app.send_task(
                "app.tasks.world_state.process_event",
                kwargs={"event_id": event_id},
                queue="critical",
            )
    except Exception as exc:
        # Correctness comes from the Postgres recovery drain, never this signal.
        logger.warning("[world-state] immediate dispatch unavailable for %d event(s): %s", len(ids), exc)


def _clear_ids(session: Session) -> None:
    session.info.pop(_EVENT_IDS_INFO_KEY, None)


def install_after_commit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    sa_event.listen(Session, "after_commit", _dispatch_ids)
    sa_event.listen(Session, "after_rollback", _clear_ids)
    _HOOK_INSTALLED = True


install_after_commit_hook()


def _build(
    *, user_id: str, kind: str, source: str, dedupe_key: str,
    payload: Optional[Dict[str, Any]] = None, source_ref: Optional[str] = None,
    aggregate_type: Optional[str] = None, aggregate_id: Optional[str] = None,
    aggregate_version: Optional[int] = None, actor_type: str = "system",
    actor_id: Optional[str] = None, correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None, occurred_at: Optional[datetime] = None,
    observed_at: Optional[datetime] = None, provenance: Optional[Dict[str, Any]] = None,
    confidence: float = 1.0, confidence_basis: str = "observed",
    sensitivity: Optional[str] = None, retention_class: Optional[str] = None,
    is_backfill: bool = False,
) -> EventEnvelopeV2:
    spec = get_spec(kind)
    now = datetime.now(timezone.utc)
    return EventEnvelopeV2(
        user_id=str(user_id), kind=kind, source=source, source_ref=source_ref,
        aggregate_type=aggregate_type, aggregate_id=str(aggregate_id) if aggregate_id is not None else None,
        aggregate_version=aggregate_version, actor_type=actor_type, actor_id=actor_id,
        correlation_id=correlation_id, causation_id=causation_id, dedupe_key=dedupe_key,
        payload=_json_safe(payload or {}), provenance=_json_safe(provenance or {}),
        occurred_at=occurred_at or now, observed_at=observed_at or now,
        confidence=max(0.0, min(float(confidence), 1.0)), confidence_basis=confidence_basis,
        sensitivity=sensitivity or spec.sensitivity, retention_class=retention_class or spec.retention_class,
        is_backfill=is_backfill,
    )


def _to_row(envelope: EventEnvelopeV2) -> WorldEvent:
    values = envelope.model_dump(exclude={"sequence", "committed_at"})
    return WorldEvent(**values)


def append_world_event(db: Session, **kwargs) -> Optional[WorldEvent]:
    """Append without committing; caller's domain transaction owns the commit."""
    if not _enabled():
        return None
    envelope = _build(**kwargs)
    existing = db.execute(select(WorldEvent).where(
        WorldEvent.user_id == envelope.user_id,
        WorldEvent.dedupe_key == envelope.dedupe_key,
    )).scalar_one_or_none()
    if existing:
        return existing
    row = _to_row(envelope)
    db.add(row)
    db.flush()
    db.add(WorldEventProcessing(event_id=row.event_id, status="pending"))
    db.flush()
    db.info.setdefault(_EVENT_IDS_INFO_KEY, []).append(row.event_id)
    return row


async def append_world_event_async(db, **kwargs) -> Optional[WorldEvent]:
    """AsyncSession equivalent; still commits atomically with the caller."""
    if not _enabled():
        return None
    envelope = _build(**kwargs)
    result = await db.execute(select(WorldEvent).where(
        WorldEvent.user_id == envelope.user_id,
        WorldEvent.dedupe_key == envelope.dedupe_key,
    ))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    row = _to_row(envelope)
    db.add(row)
    await db.flush()
    db.add(WorldEventProcessing(event_id=row.event_id, status="pending"))
    await db.flush()
    db.sync_session.info.setdefault(_EVENT_IDS_INFO_KEY, []).append(row.event_id)
    return row

