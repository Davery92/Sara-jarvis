"""Authenticated world-state, presence, and diagnostic endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.world_model import (
    WorldAttentionItem, WorldEvent, WorldEventDisposition, WorldEventProcessing,
)
from app.services.world_state.context import build_context_bundle, get_presence, get_snapshot

router = APIRouter(prefix="/api/world-state", tags=["world-state"])


@router.get("/presence")
def presence(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return get_presence(db, str(current_user.id)).model_dump(mode="json")


@router.get("/snapshot")
def snapshot(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return get_snapshot(db, str(current_user.id)).model_dump(mode="json")


@router.get("/context")
def context(conversation_id: str | None = None, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return build_context_bundle(db, str(current_user.id), conversation_id=conversation_id).model_dump(mode="json")


@router.get("/events")
def events(
    after_sequence: int = 0, limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
):
    rows = db.execute(select(WorldEvent).where(
        WorldEvent.user_id == str(current_user.id), WorldEvent.sequence > after_sequence,
    ).order_by(WorldEvent.sequence.asc()).limit(limit)).scalars().all()
    return {"events": [{
        "sequence": r.sequence, "event_id": r.event_id, "kind": r.kind,
        "occurred_at": r.occurred_at.isoformat(), "observed_at": r.observed_at.isoformat(),
        "source": r.source, "source_ref": r.source_ref, "aggregate_id": r.aggregate_id,
        "correlation_id": r.correlation_id, "confidence": r.confidence,
        "confidence_basis": r.confidence_basis, "payload": r.payload,
    } for r in rows]}


@router.get("/trace/{event_id}")
def trace(event_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    event = db.execute(select(WorldEvent).where(
        WorldEvent.event_id == event_id, WorldEvent.user_id == str(current_user.id),
    )).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="World event not found")
    processing = db.execute(select(WorldEventProcessing).where(WorldEventProcessing.event_id == event_id)).scalar_one_or_none()
    disposition = db.execute(select(WorldEventDisposition).where(WorldEventDisposition.event_id == event_id)).scalar_one_or_none()
    return {
        "event": {"sequence": event.sequence, "event_id": event.event_id, "kind": event.kind, "payload": event.payload},
        "processing": None if processing is None else {"status": processing.status, "attempt_count": processing.attempt_count, "last_error": processing.last_error, "interpreter_status": processing.interpreter_status},
        "disposition": None if disposition is None else {"outcomes": disposition.outcomes, "reason": disposition.reason, "state_delta": disposition.state_delta, "output_ids": disposition.output_ids},
    }


@router.get("/health")
def health(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    uid = str(current_user.id)
    latest = db.execute(select(func.max(WorldEvent.sequence)).where(WorldEvent.user_id == uid)).scalar() or 0
    pending = db.execute(select(func.count()).select_from(WorldEventProcessing).join(WorldEvent).where(
        WorldEvent.user_id == uid, WorldEventProcessing.status.in_(("pending", "retry", "leased")),
    )).scalar() or 0
    dead = db.execute(select(func.count()).select_from(WorldEventProcessing).join(WorldEvent).where(
        WorldEvent.user_id == uid, WorldEventProcessing.status == "dead_letter",
    )).scalar() or 0
    # Interpretations that hit the attempt cap. Surfaced so a give-up is visible
    # instead of an event quietly vanishing from the drain.
    interp_failed = db.execute(select(func.count()).select_from(WorldEventProcessing).join(WorldEvent).where(
        WorldEvent.user_id == uid, WorldEventProcessing.interpreter_status == "failed",
    )).scalar() or 0
    attention = db.execute(select(func.count()).select_from(WorldAttentionItem).where(
        WorldAttentionItem.user_id == uid, WorldAttentionItem.status == "queued",
    )).scalar() or 0
    snap = get_snapshot(db, uid)
    return {"now": datetime.now(timezone.utc).isoformat(), "latest_sequence": int(latest), "projected_sequence": snap.last_event_sequence, "lag_events": max(0, int(latest) - snap.last_event_sequence), "pending": int(pending), "dead_letters": int(dead), "interpreter_failed": int(interp_failed), "queued_attention": int(attention)}
