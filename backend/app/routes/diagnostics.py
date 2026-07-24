"""Diagnostics API — read-only vitals for the webapp System view (Phase 2).

Mirrors the chat diagnostics tools over HTTP so the webapp can render a vitals
strip: failing tasks, error counts, queue depths, drift, and version-match.
All read-only; no endpoint mutates Sara's state.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.services import diagnostics_service as diag

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


@router.get("/overview")
async def overview(current_user=Depends(get_current_user)):
    return await diag.diagnostics_overview()


@router.get("/failures")
async def failures(hours: int = 24, include_resolved: bool = False,
                   current_user=Depends(get_current_user)):
    return {"failures": await diag.get_failing_tasks(hours=hours, include_resolved=include_resolved)}


@router.get("/events")
async def events(service: Optional[str] = None, level: Optional[str] = None,
                 since_hours: int = 24, query: Optional[str] = None, limit: int = 50,
                 current_user=Depends(get_current_user)):
    return {"events": await diag.search_events(service=service, level=level,
                                               since_hours=since_hours, query=query, limit=limit)}


@router.get("/explain/{event_id}")
async def explain(event_id: str, current_user=Depends(get_current_user)):
    detail = await diag.explain_event(event_id)
    if not detail:
        raise HTTPException(status_code=404, detail="event not found")
    return detail


class ReportIn(BaseModel):
    topic: str = "system health"


@router.post("/report")
async def report(payload: ReportIn, current_user=Depends(get_current_user)):
    md = await diag.build_report(payload.topic)
    return {"topic": payload.topic, "markdown": md}


@router.get("/truth-audit")
async def truth_audit(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Read-only scan for impossible state combinations across the
    intent/action surfaces that already exist (missions, background tasks) —
    SINGULAR_SARA_MASTER_PLAN §13 item 4. Finds violations; fixes them
    nowhere yet."""
    from app.services.truth_audit import run_truth_audit
    return run_truth_audit(db)


@router.get("/body-state")
async def body_state(current_user=Depends(get_current_user)):
    """The canonical body-state projection (SINGULAR_SARA_MASTER_PLAN §13
    item 3) — the same merged health verdict `/api/sara/brief`,
    `/api/metrics`, and `/analytics/dashboard` read, exposed directly for
    inspection."""
    from app.services.body_state_projection import get_body_state_projection
    projection = await get_body_state_projection(str(current_user.id))
    return projection.model_dump(mode="json")


@router.get("/feature-flags")
async def feature_flags(current_user=Depends(get_current_user)):
    """Current state of every SINGULAR_SARA kill switch (§C0). All default
    OFF until a phase's exit gate is actually met."""
    from app.core.feature_flags import all_flags
    return {"flags": all_flags()}


@router.get("/path-counters")
async def path_counters(path_name: str = "ambient_cognition", days: int = 7,
                        current_user=Depends(get_current_user)):
    """Legacy-vs-target traffic for one migration path (§C0 counters) — e.g.
    how often ambient cognition still bypasses `kernel.ambient_turn`."""
    from app.services.legacy_path_counters import get_counts
    return await get_counts(path_name, days=days)


@router.get("/recent-events")
async def recent_events(limit: int = 20, current_user=Depends(get_current_user)):
    """Most recent canonical EventEnvelopeV1 records for the current user
    (SINGULAR_SARA_MASTER_PLAN §C1) — every event published on the real
    event bus, translated into one traceable shape with provenance and a
    dedupe key, regardless of which subsystem published it."""
    from app.services.event_envelope_adapter import get_recent_envelopes
    envelopes = await get_recent_envelopes(str(current_user.id), limit=limit)
    return {"events": [e.model_dump(mode="json") for e in envelopes]}


@router.get("/intent-graph")
async def intent_graph(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Read-only projection of everything Sara currently considers open —
    reminders, standing orders, missions, waiting threads, background tasks,
    and Sara's own interests — as one list of IntentV1 (SINGULAR_SARA_MASTER_
    PLAN §13/§C3). Nothing here is a new truth store; it reads existing
    tables and does not migrate or write anything."""
    from app.services.intent_graph_projection import get_intent_graph
    return get_intent_graph(db, str(current_user.id))


@router.post("/scheduler-diet/backfill")
async def backfill_scheduler_diet(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Classify every `scheduled_job` row and persist it to
    `singular_class` (SINGULAR_SARA_MASTER_PLAN §C11). Idempotent."""
    from app.services.scheduler_diet import backfill_singular_class
    return backfill_singular_class(db)


@router.get("/scheduler-diet")
async def scheduler_diet(singular_class: Optional[str] = None, db: Session = Depends(get_db),
                         current_user=Depends(get_current_user)):
    """Scheduled jobs, optionally filtered by their persisted singular_class."""
    from app.services.scheduler_diet import list_by_class
    return {"jobs": list_by_class(db, singular_class)}


@router.get("/action-receipts")
async def action_receipts(limit: int = 20, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Recent shadow-recorded action receipts (SINGULAR_SARA_MASTER_PLAN
    §C10) — permission tier + true status (never a bare success flag) for
    executed actions, alongside the existing action_ledger."""
    from app.services.action_receipt_service import list_recent_receipts
    return {"receipts": list_recent_receipts(db, str(current_user.id), limit=limit)}


@router.get("/attention-log")
async def attention_log(limit: int = 20, current_user=Depends(get_current_user)):
    """Recent shadow-recorded outbound-intent/attention-item pairs
    (SINGULAR_SARA_MASTER_PLAN §C9) — what `send_notification()` actually
    decided and delivered, in the canonical shape, for inspection."""
    from app.db.session import get_async_session_factory
    from sqlalchemy import text

    async_session = get_async_session_factory()
    async with async_session() as db:
        rows = (await db.execute(text("""
            SELECT oi.outbound_intent_id, oi.subject, oi.why_now, oi.created_at,
                   ai.decision, ai.rendered_text, ai.delivered_channels, ai.delivered_at
            FROM outbound_intent oi
            JOIN attention_item ai ON ai.outbound_intent_id = oi.outbound_intent_id
            WHERE oi.user_id = :uid
            ORDER BY oi.created_at DESC
            LIMIT :lim
        """), {"uid": str(current_user.id), "lim": limit})).mappings().all()
        return {"items": [dict(r) for r in rows]}


@router.get("/body-capabilities")
async def body_capabilities(current_user=Depends(get_current_user)):
    """Every known execution body — VM workshop, acs-tool-runner, managed
    hosts, Proxmox sandboxes — and whether it's currently alive
    (SINGULAR_SARA_MASTER_PLAN §C7)."""
    from app.db.session import get_async_session_factory
    from app.services.body_capability_service import list_capabilities

    async_session = get_async_session_factory()
    async with async_session() as db:
        return {"bodies": await list_capabilities(db)}


@router.get("/context-snapshot")
async def context_snapshot(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """One assembled world/self/relationship snapshot (SINGULAR_SARA_MASTER_
    PLAN §13/§4.2/§C2) — the remaining three quadrants of context state
    alongside the canonical body-state projection. Read-only; nothing routes
    through this yet."""
    from app.services.context_snapshot import get_context_snapshot
    return await get_context_snapshot(db, str(current_user.id))


@router.post("/intent-graph/sync")
async def sync_intent_graph(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Upsert the read-only intent projection into the real, durable
    `intent` table (SINGULAR_SARA_MASTER_PLAN §C3). Idempotent — safe to
    call repeatedly; only ever inserts/updates, never deletes."""
    from app.services.intent_graph_service import sync_from_projections
    return sync_from_projections(db, str(current_user.id))


@router.get("/intent-graph/persisted")
async def persisted_intent_graph(status: Optional[str] = None, db: Session = Depends(get_db),
                                 current_user=Depends(get_current_user)):
    """The real, durable `intent` table contents (as opposed to the live
    re-computed projection at /intent-graph)."""
    from app.services.intent_graph_service import list_intents
    return {"intents": list_intents(db, str(current_user.id), status=status)}
