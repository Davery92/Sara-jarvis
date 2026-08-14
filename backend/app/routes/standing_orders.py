"""
Standing Orders API Route

Exposes active standing orders for the dashboard.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.deps import get_current_user
from app.core.timezone import now as local_now, to_local

logger = logging.getLogger(__name__)

router = APIRouter(tags=["standing-orders"])


def compute_order_fires_at(db: Session, user_id: str, trigger_type: str, trigger_config: Optional[Dict[str, Any]]):
    """Best-effort next-fire datetime (ET-aware) for a standing order's
    trigger. Returns None for triggers without a deterministic schedule
    (climate/presence/calendar/state/compound) — those aren't a "next fires
    at" moment, they're conditional.

    Shared by /api/standing-orders and /api/sara/brief's `ongoing` section so
    the two never disagree about when something fires.
    """
    if not trigger_config:
        return None
    if trigger_type == "timer":
        timer_title = trigger_config.get("timer_title")
        if not timer_title:
            return None
        timer_row = db.execute(text("""
            SELECT end_time FROM timer
            WHERE user_id = :uid AND title = :title
              AND is_active = true AND is_completed = false
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": user_id, "title": timer_title}).fetchone()
        return to_local(timer_row.end_time) if timer_row and timer_row.end_time else None
    if trigger_type == "time":
        hour = trigger_config.get("hour")
        if hour is None:
            return None
        minute = trigger_config.get("minute", 0)
        now_et = local_now()
        candidate = now_et.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if candidate <= now_et:
            candidate += timedelta(days=1)
        return candidate
    return None


@router.get("/api/standing-orders")
async def list_standing_orders(
    status: str = Query("active"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List standing orders filtered by status."""
    user_id = str(current_user.id)
    try:
        rows = db.execute(
            text("""
                SELECT id, description, trigger_type, trigger_config,
                       action_type, action_config, source, status,
                       last_executed_at, execution_count, created_at
                FROM standing_order
                WHERE user_id = :uid AND status = :status
                ORDER BY created_at DESC
            """),
            {"uid": user_id, "status": status},
        ).fetchall()

        orders = []
        for r in rows:
            import json
            tc = r.trigger_config
            ac = r.action_config
            if isinstance(tc, str):
                tc = json.loads(tc)
            if isinstance(ac, str):
                ac = json.loads(ac)

            order = {
                "id": r.id,
                "description": r.description,
                "trigger_type": r.trigger_type,
                "trigger_config": tc or {},
                "action_type": r.action_type,
                "action_config": ac or {},
                "source": r.source,
                "status": r.status,
                "last_executed_at": r.last_executed_at.isoformat() if r.last_executed_at else None,
                "execution_count": r.execution_count or 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }

            fires_at = compute_order_fires_at(db, user_id, r.trigger_type, tc)
            if fires_at:
                order["fires_at"] = fires_at.isoformat()

            # For time-triggered orders, also show the scheduled time
            if r.trigger_type == "time" and tc:
                hour = tc.get("hour")
                minute = tc.get("minute", 0)
                if hour is not None:
                    order["scheduled_time"] = f"{hour:02d}:{minute:02d}"
                    days = tc.get("days")
                    if days:
                        order["scheduled_days"] = days

            orders.append(order)

        return {"orders": orders, "count": len(orders)}
    except Exception as e:
        logger.warning("Failed to load standing orders: %s", e)
        return {"orders": [], "count": 0}
