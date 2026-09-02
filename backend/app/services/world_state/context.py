"""Read bounded, durable context from continuously maintained projections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.world_model import (
    SaraPresenceSnapshot, WorldEvent, WorldFact, WorldSnapshot, WorldThread,
)
from app.schemas.world_events import ContextBundleV2, SaraPresenceV1, WorldSnapshotV2
from app.services.world_state.coordinator import catch_up_user


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_presence(db: Session, user_id: str) -> SaraPresenceV1:
    now = _now()
    row = db.execute(
        select(SaraPresenceSnapshot).where(SaraPresenceSnapshot.user_id == str(user_id))
    ).scalar_one_or_none()
    if row is None:
        return SaraPresenceV1(user_id=str(user_id), updated_at=now, valid_until=now + timedelta(minutes=5))
    expired = row.valid_until <= now
    return SaraPresenceV1(
        user_id=str(user_id), revision=row.revision,
        state="resting" if expired else row.state,
        headline="Available" if expired else row.headline,
        detail=None if expired else row.detail,
        source=row.source, correlation_id=row.correlation_id,
        event_id=row.event_id, task_id=None if expired else row.task_id,
        updated_at=row.updated_at,
        valid_until=(now + timedelta(minutes=5)) if expired else row.valid_until,
    )


def get_snapshot(db: Session, user_id: str) -> WorldSnapshotV2:
    now = _now()
    row = db.execute(
        select(WorldSnapshot).where(WorldSnapshot.user_id == str(user_id))
    ).scalar_one_or_none()
    if row is None:
        return WorldSnapshotV2(user_id=str(user_id), as_of=now)
    body = dict(row.snapshot or {})
    return WorldSnapshotV2(
        user_id=str(user_id), revision=row.revision,
        last_event_sequence=row.last_event_sequence, as_of=row.as_of,
        slices=body.get("slices") or {}, recent_changes=body.get("recent_changes") or [],
        coverage=row.coverage or {},
    )


def build_context_bundle(
    db: Session, user_id: str, *, conversation_id: Optional[str] = None,
    catch_up_limit: int = 50, recent_limit: int = 30, fact_limit: int = 80,
    thread_limit: int = 30,
) -> ContextBundleV2:
    caught = catch_up_user(db, str(user_id), limit=catch_up_limit)
    snapshot = get_snapshot(db, str(user_id))
    latest = db.execute(
        select(func.max(WorldEvent.sequence)).where(WorldEvent.user_id == str(user_id))
    ).scalar() or 0
    events = db.execute(
        select(WorldEvent)
        .where(WorldEvent.user_id == str(user_id))
        .order_by(WorldEvent.sequence.desc()).limit(recent_limit)
    ).scalars().all()
    facts = db.execute(
        select(WorldFact)
        .where(WorldFact.user_id == str(user_id), WorldFact.status == "active")
        .order_by(WorldFact.last_event_sequence.desc()).limit(fact_limit)
    ).scalars().all()
    threads = db.execute(
        select(WorldThread)
        .where(WorldThread.user_id == str(user_id), WorldThread.status.in_(("proposed", "open", "waiting", "blocked")))
        .order_by(WorldThread.priority.desc(), WorldThread.updated_at.desc()).limit(thread_limit)
    ).scalars().all()
    return ContextBundleV2(
        user_id=str(user_id), conversation_id=conversation_id, built_at=_now(),
        snapshot_revision=snapshot.revision,
        last_event_sequence=snapshot.last_event_sequence,
        latest_committed_sequence=int(latest),
        caught_up_inline=bool(caught["attempted"]), complete=bool(caught["complete"]),
        snapshot=snapshot.model_dump(mode="json"),
        recent_deltas=[{
            "sequence": e.sequence, "event_id": e.event_id, "kind": e.kind,
            "occurred_at": e.occurred_at.isoformat(), "summary": _summary(e.payload, e.kind),  # time-ok: structured bundle for code, never a prompt
            "source_ref": e.source_ref,
        } for e in reversed(events)],
        relevant_facts=[{
            "id": f.id, "predicate": f.predicate, "value": f.value,
            "confidence": f.confidence, "confidence_basis": f.confidence_basis,
            "valid_from": f.valid_from.isoformat() if f.valid_from else None,  # time-ok: structured bundle for code, never a prompt
            "source_ref": f.source_ref,
        } for f in facts],
        active_threads=[{
            "id": t.id, "kind": t.kind, "status": t.status, "title": t.title,
            "next_step": t.next_step, "due_at": t.due_at.isoformat() if t.due_at else None,  # time-ok: structured bundle for code, never a prompt
            "priority": t.priority, "confidence": t.confidence,
        } for t in threads],
    )


def _summary(payload: Dict[str, Any], kind: str) -> str:
    for key in ("summary", "status_label", "subject", "title", "name", "preview"):
        if payload.get(key):
            return str(payload[key])[:240]
    return kind.replace(".", " ")


# `format_context_for_prompt` used to live here: a 14,000-character JSON dump of
# the whole projection, truncated mid-word, injected into every chat turn and
# every deliberation. It cost 7-8k uncacheable tokens a turn and flattened a light
# switch, an AWS invoice and a real meeting into one undifferentiated blob.
#
# Deleted, not replaced. Prompts read the prose World Brief
# (`world_brief.get_rendered_brief`), where every time is rendered in ET and
# nothing is JSON. `build_context_bundle` above is still the structured read for
# code; it is not for models.
