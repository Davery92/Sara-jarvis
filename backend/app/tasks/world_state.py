"""Celery entry points for Sara's always-on world-state runtime."""

import asyncio

from app.celery_app import celery_app
from app.db.session import SessionLocal


@celery_app.task(name="app.tasks.world_state.process_event", acks_late=True)
def process_event(event_id: str):
    from app.services.world_state.coordinator import process_one
    with SessionLocal() as db:
        return process_one(db, event_id)


@celery_app.task(name="app.tasks.world_state.drain_pending_events", acks_late=True)
def drain_pending_events(limit: int = 100):
    from app.services.world_state.coordinator import drain_pending
    with SessionLocal() as db:
        return drain_pending(db, limit=limit)


@celery_app.task(name="app.tasks.world_state.synthesize_temporal_events", acks_late=True)
def synthesize_temporal_events():
    from app.services.world_state.temporal import synthesize
    with SessionLocal() as db:
        return synthesize(db)


@celery_app.task(name="app.tasks.world_state.interpret_event", acks_late=True)
def interpret_event(event_id: str):
    from app.services.world_state.interpreter import run_interpretation
    with SessionLocal() as db:
        return run_interpretation(db, event_id)


@celery_app.task(name="app.tasks.world_state.drain_interpretations", acks_late=True)
def drain_interpretations(limit: int = 20):
    from sqlalchemy import select
    from app.models.world_model import WorldEventProcessing

    with SessionLocal() as db:
        ids = list(db.execute(
            select(WorldEventProcessing.event_id)
            .where(
                WorldEventProcessing.status == "completed",
                WorldEventProcessing.interpreter_status.in_(("pending", "retry")),
            )
            .order_by(WorldEventProcessing.updated_at.asc())
            .limit(max(1, min(int(limit), 100)))
        ).scalars().all())
    for pending_id in ids:
        celery_app.send_task(
            "app.tasks.world_state.interpret_event",
            kwargs={"event_id": pending_id},
            queue="cognitive",
        )
    return {"dispatched": len(ids)}


async def _consider_attention(user_id: str):
    from app.services.kernel import WakeReason, ambient_turn
    from app.services.world_state.cognition import mirror_pending_attention

    mirrored = await mirror_pending_attention(str(user_id))
    if not mirrored["mirrored"]:
        return {"effect": "nothing_queued"}
    result = await ambient_turn(str(user_id), wake_reason=WakeReason.PROMOTED_EVENT)
    return {"effect": "considered", **mirrored, "kernel": result}


@celery_app.task(name="app.tasks.world_state.consider_attention", acks_late=True)
def consider_attention(user_id: str):
    return asyncio.run(_consider_attention(str(user_id)))


@celery_app.task(name="app.tasks.world_state.drain_attention", acks_late=True)
def drain_attention(limit: int = 20):
    from sqlalchemy import distinct, select
    from app.models.world_model import WorldAttentionItem

    with SessionLocal() as db:
        user_ids = list(db.execute(
            select(distinct(WorldAttentionItem.user_id))
            .where(WorldAttentionItem.status == "queued")
            .limit(max(1, min(int(limit), 100)))
        ).scalars().all())
    for user_id in user_ids:
        celery_app.send_task(
            "app.tasks.world_state.consider_attention",
            kwargs={"user_id": str(user_id)},
            queue="cognitive",
        )
    return {"dispatched": len(user_ids)}


@celery_app.task(name="app.tasks.world_state.deliver_presence", acks_late=True)
def deliver_presence(user_id: str, event_id: str | None = None):
    from app.services.world_state.presence_delivery import deliver
    with SessionLocal() as db:
        return asyncio.run(deliver(db, str(user_id), event_id=event_id))
