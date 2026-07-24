"""
Periodic intent-graph sync (SINGULAR_SARA_MASTER_PLAN §C3).

The real, durable `intent` table only stayed current through a manual
`POST /api/diagnostics/intent-graph/sync` call — this task is that same
idempotent sync, running on a schedule, so "one intent graph" reflects
reality without anyone remembering to poke it. Read-only over the source
tables (reminder/standing_order/autonomy_mission/followup_thread/
background_task/sara_interest); only ever upserts into `intent`.
"""
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@celery_app.task(name="app.tasks.intent_graph.sync_intent_graph")
def sync_intent_graph():
    """Upsert the live intent-graph projection into the durable `intent`
    table. Outcome contract: {"effect": "intent_graph_synced", ...}."""
    from app.db.session import SessionLocal
    from app.services.intent_graph_service import sync_from_projections

    db = SessionLocal()
    try:
        result = sync_from_projections(db, DAVID_USER_ID)
    finally:
        db.close()

    logger.info(
        "Intent graph sync: seen=%d upserted=%d errors=%d",
        result["seen"], result["upserted"], len(result["errors"]),
    )
    return {
        "effect": "intent_graph_synced",
        "seen": result["seen"],
        "upserted": result["upserted"],
        "error_count": len(result["errors"]),
    }
