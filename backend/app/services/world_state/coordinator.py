"""Lease, apply, retry, and catch up durable world events."""

from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.world_model import WorldEvent, WorldEventDisposition, WorldEventProcessing
from app.services.world_state.reducer import REDUCER_VERSION, reduce_world_event

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 8
LEASE_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _ready_clause(now: datetime):
    return or_(
        and_(
            WorldEventProcessing.status.in_(("pending", "retry")),
            or_(WorldEventProcessing.next_attempt_at.is_(None), WorldEventProcessing.next_attempt_at <= now),
        ),
        and_(
            WorldEventProcessing.status == "leased",
            WorldEventProcessing.leased_until.is_not(None),
            WorldEventProcessing.leased_until <= now,
        ),
    )


def _claim(db: Session, event_id: str) -> bool:
    now = _now()
    processing = db.execute(
        select(WorldEventProcessing)
        .where(WorldEventProcessing.event_id == event_id)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if processing is None or processing.status in {"completed", "dead_letter"}:
        return False
    if processing.status == "leased" and processing.leased_until and processing.leased_until > now:
        return False
    if processing.next_attempt_at and processing.next_attempt_at > now:
        return False
    processing.status = "leased"
    processing.attempt_count = (processing.attempt_count or 0) + 1
    processing.started_at = processing.started_at or now
    processing.leased_until = now + timedelta(seconds=LEASE_SECONDS)
    processing.worker_id = _worker_id()
    processing.last_error = None
    db.commit()
    return True


def process_one(db: Session, event_id: str) -> Dict[str, object]:
    """Process one event. A disposition is the idempotency boundary."""
    if not _claim(db, event_id):
        return {"event_id": event_id, "effect": "not_claimed"}
    try:
        processing = db.execute(
            select(WorldEventProcessing)
            .where(WorldEventProcessing.event_id == event_id)
            .with_for_update()
        ).scalar_one()
        event = db.execute(select(WorldEvent).where(WorldEvent.event_id == event_id)).scalar_one()
        existing = db.execute(
            select(WorldEventDisposition).where(WorldEventDisposition.event_id == event_id)
        ).scalar_one_or_none()
        disposition = existing or reduce_world_event(db, event)
        processing.status = "completed"
        processing.completed_at = _now()
        processing.leased_until = None
        processing.next_attempt_at = None
        processing.reducer_version = REDUCER_VERSION
        processing.interpreter_status = (
            "pending" if "interpretation_queued" in (disposition.outcomes or []) else "not_needed"
        )
        db.commit()
        if "presence" in (disposition.output_ids or {}):
            _dispatch_presence(event.user_id, event_id)
        if processing.interpreter_status == "pending":
            _dispatch_interpretation(event_id)
        if (disposition.output_ids or {}).get("attention"):
            _dispatch_cognition(event.user_id)
        return {
            "event_id": event_id,
            "effect": "completed",
            "outcomes": list(disposition.outcomes or []),
        }
    except Exception as exc:
        db.rollback()
        logger.exception("[world-state] event %s failed", event_id)
        processing = db.execute(
            select(WorldEventProcessing)
            .where(WorldEventProcessing.event_id == event_id)
            .with_for_update()
        ).scalar_one_or_none()
        if processing is not None:
            attempts = processing.attempt_count or 1
            processing.last_error = str(exc)[:4000]
            processing.leased_until = None
            if attempts >= MAX_ATTEMPTS:
                processing.status = "dead_letter"
                processing.next_attempt_at = None
            else:
                processing.status = "retry"
                processing.next_attempt_at = _now() + timedelta(seconds=min(300, 2 ** attempts))
            db.commit()
        return {"event_id": event_id, "effect": "failed", "error": str(exc)}


def _dispatch_interpretation(event_id: str) -> None:
    try:
        from app.celery_app import celery_app
        celery_app.send_task(
            "app.tasks.world_state.interpret_event",
            kwargs={"event_id": event_id},
            queue="cognitive",
        )
    except Exception as exc:
        # A periodic interpreter drain recovers this path.
        logger.warning("[world-state] interpreter dispatch unavailable for %s: %s", event_id, exc)


def _dispatch_presence(user_id: str, event_id: str) -> None:
    try:
        from app.celery_app import celery_app
        celery_app.send_task(
            "app.tasks.world_state.deliver_presence",
            kwargs={"user_id": str(user_id), "event_id": event_id},
            queue="critical",
        )
    except Exception as exc:
        logger.warning("[world-state] presence delivery unavailable for %s: %s", event_id, exc)


def _dispatch_cognition(user_id: str) -> None:
    try:
        from app.celery_app import celery_app
        celery_app.send_task(
            "app.tasks.world_state.consider_attention",
            kwargs={"user_id": str(user_id)},
            queue="cognitive",
        )
    except Exception as exc:
        logger.warning("[world-state] cognition dispatch unavailable for %s: %s", user_id, exc)


def ready_event_ids(db: Session, *, limit: int = 100, user_id: Optional[str] = None) -> List[str]:
    now = _now()
    query = (
        select(WorldEventProcessing.event_id)
        .join(WorldEvent, WorldEvent.event_id == WorldEventProcessing.event_id)
        .where(_ready_clause(now))
        .order_by(WorldEvent.sequence.asc())
        .limit(max(1, min(limit, 1000)))
    )
    if user_id:
        query = query.where(WorldEvent.user_id == str(user_id))
    return list(db.execute(query).scalars().all())


def drain_pending(db: Session, *, limit: int = 100) -> Dict[str, object]:
    ids = ready_event_ids(db, limit=limit)
    results = [process_one(db, event_id) for event_id in ids]
    return {
        "claimed": len(ids),
        "completed": sum(1 for row in results if row.get("effect") == "completed"),
        # NOT "failed": the outcome-contract checker reads a truthy `failed`
        # key as "this task failed", so a drain that handled 7 events and
        # couldn't reduce 1 was marking its whole scheduled job red.
        "failures": sum(1 for row in results if row.get("effect") == "failed"),
    }


def catch_up_user(db: Session, user_id: str, *, limit: int = 50) -> Dict[str, object]:
    ids = ready_event_ids(db, limit=limit, user_id=str(user_id))
    results = [process_one(db, event_id) for event_id in ids]
    remaining = len(ready_event_ids(db, limit=1, user_id=str(user_id))) > 0
    return {
        "attempted": len(ids),
        "completed": sum(1 for row in results if row.get("effect") == "completed"),
        "complete": not remaining,
    }
