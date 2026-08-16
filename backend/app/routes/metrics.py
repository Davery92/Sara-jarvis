"""
System metrics endpoint — aggregates health, LLM, ACS, task, and notification data.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


def _get_db():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/api/metrics")
async def get_metrics(db: Session = Depends(_get_db)):
    """Comprehensive system metrics snapshot."""
    from app.core.redis import get_redis_sync
    r = get_redis_sync()
    user_id = os.getenv("SOLO_USER_ID", "")
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    metrics = {}

    # Health status from last heartbeat
    try:
        raw = r.get("system:health_status")
        metrics["health"] = json.loads(raw) if raw else {"overall_status": "unknown"}
    except Exception:
        metrics["health"] = {"overall_status": "unknown"}

    # Canonical body-state projection (SINGULAR_SARA_MASTER_PLAN §13 item 3) —
    # the same merged verdict `/api/sara/brief` and `/analytics/dashboard`
    # read, so this endpoint's health picture can't silently diverge from
    # theirs. `health` above is left untouched (raw heartbeat report; the
    # System Status page reads `health.checks` directly).
    try:
        from app.services.body_state_projection import get_body_state_projection
        projection = await get_body_state_projection(user_id) if user_id else await get_body_state_projection()
        metrics["body_state"] = projection.model_dump(mode="json")
    except Exception as e:
        metrics["body_state"] = {"error": str(e)[:100]}

    # LLM status
    try:
        from app.core.llm import get_background_llm_client
        bg = get_background_llm_client()
        metrics["llm"] = {
            "background": bg.get_status(),
        }
    except Exception as e:
        metrics["llm"] = {"error": str(e)[:100]}

    # ACS status
    try:
        acs_state = r.get(f"sara:acs:state:{user_id}")
        acs_session = r.get(f"sara:acs:active_session:{user_id}")

        result = db.execute(text("""
            SELECT count(*) as total,
                   count(*) FILTER (WHERE end_reason = 'error') as errors,
                   avg(turns_completed) as avg_turns,
                   sum(notes_created) as total_notes
            FROM acs_session
            WHERE started_at > :since AND user_id = :uid
        """), {"since": day_ago, "uid": user_id})
        row = result.fetchone()

        metrics["acs"] = {
            "state": acs_state or "unknown",
            "active_session": acs_session,
            "sessions_24h": row[0] if row else 0,
            "errors_24h": row[1] if row else 0,
            "error_rate_24h": round(row[1] / max(row[0], 1), 2) if row else 0,
            "avg_turns_24h": round(row[2] or 0, 1) if row else 0,
            "notes_24h": row[3] if row else 0,
        }
    except Exception as e:
        metrics["acs"] = {"error": str(e)[:100]}

    # Queue depths
    try:
        queues = ["critical", "cognitive", "health", "input", "maintenance", "low_priority", "reflection", "acs"]
        depths = {}
        for q in queues:
            depths[q] = r.llen(q) or 0
        metrics["queues"] = depths
    except Exception as e:
        metrics["queues"] = {"error": str(e)[:100]}

    # Notifications
    try:
        result = db.execute(text("""
            SELECT count(*) as sent,
                   count(*) FILTER (WHERE engaged = true) as engaged
            FROM notification_log
            WHERE sent_at > :since AND user_id = :uid AND sent = true
        """), {"since": day_ago, "uid": user_id})
        row = result.fetchone()
        sent = row[0] if row else 0
        engaged = row[1] if row else 0
        metrics["notifications"] = {
            "sent_24h": sent,
            "engaged_24h": engaged,
            "engagement_rate": round(engaged / max(sent, 1), 2),
        }
    except Exception as e:
        metrics["notifications"] = {"error": str(e)[:100]}

    # Memory
    try:
        ep_total = db.execute(text("SELECT count(*) FROM episode WHERE user_id = :uid"), {"uid": user_id}).scalar()
        ep_24h = db.execute(text("SELECT count(*) FROM episode WHERE user_id = :uid AND created_at > :since"), {"uid": user_id, "since": day_ago}).scalar()
        metrics["memory"] = {
            "episodes_total": ep_total or 0,
            "episodes_24h": ep_24h or 0,
        }
    except Exception as e:
        metrics["memory"] = {"error": str(e)[:100]}

    # Interest graph
    try:
        nodes = db.execute(text("SELECT count(*) FROM acs_interest_node WHERE user_id = :uid AND status = 'active'"), {"uid": user_id}).scalar()
        edges = db.execute(text("SELECT count(*) FROM acs_interest_edge")).scalar()
        metrics["interest_graph"] = {"active_nodes": nodes or 0, "edges": edges or 0}
    except Exception as e:
        metrics["interest_graph"] = {"error": str(e)[:100]}

    metrics["timestamp"] = now.isoformat()
    return metrics
