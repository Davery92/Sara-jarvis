"""
Standing Orders API Route

Exposes active standing orders for the dashboard.
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["standing-orders"])


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

            # For timer-triggered orders, look up the associated timer's end time
            if r.trigger_type == "timer" and tc:
                timer_title = tc.get("timer_title")
                if timer_title:
                    timer_row = db.execute(text("""
                        SELECT end_time FROM timer
                        WHERE user_id = :uid AND title = :title
                          AND is_active = true AND is_completed = false
                        ORDER BY created_at DESC LIMIT 1
                    """), {"uid": user_id, "title": timer_title}).fetchone()
                    if timer_row and timer_row.end_time:
                        order["fires_at"] = timer_row.end_time.isoformat()

            # For time-triggered orders, show the scheduled time
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
