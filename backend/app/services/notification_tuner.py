"""
Notification Tuner — adjusts notification frequency based on engagement data.

Runs as a daily Celery task. Computes per-category engagement rates over 30 days,
then adjusts cooldowns for categories that are consistently ignored.
"""

import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def compute_and_apply_tuning(user_id: str) -> Dict[str, Any]:
    """
    Compute engagement rates per notification category and adjust cooldowns.

    Returns summary of adjustments made.
    """
    from app.db.session import get_async_session_factory
    from sqlalchemy import text

    async_session = get_async_session_factory()
    adjustments = {}

    async with async_session() as db:
        # Get per-category engagement rates over last 30 days
        result = await db.execute(text("""
            SELECT category,
                   COUNT(*) FILTER (WHERE sent = true) as sent,
                   COUNT(*) FILTER (WHERE engaged = true) as engaged,
                   COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL) as dismissed
            FROM notification_log
            WHERE user_id = :uid
              AND sent_at > NOW() - INTERVAL '30 days'
            GROUP BY category
            HAVING COUNT(*) FILTER (WHERE sent = true) >= 5
        """), {"uid": user_id})
        rows = result.fetchall()

        # Categories that should never be suppressed
        protected = {"system_health", "security", "timer", "reminder"}

        for row in rows:
            category, sent, engaged, dismissed = row[0], row[1], row[2], row[3]
            if category in protected:
                continue

            engagement_rate = engaged / max(sent, 1)
            dismiss_rate = dismissed / max(sent, 1)

            action = None
            if engagement_rate < 0.05 and sent >= 10:
                action = "suppress"  # < 5% engagement — stop sending
            elif engagement_rate < 0.15 and sent >= 10:
                action = "double_cooldown"  # < 15% — slow down
            elif engagement_rate > 0.60:
                action = "boost"  # > 60% — user wants these

            if action:
                adjustments[category] = {
                    "action": action,
                    "engagement_rate": round(engagement_rate, 3),
                    "dismiss_rate": round(dismiss_rate, 3),
                    "sent_30d": sent,
                    "engaged_30d": engaged,
                }
                logger.info(
                    f"Notification tuner: {category} -> {action} "
                    f"(engagement={engagement_rate:.0%}, sent={sent})"
                )

    # Store adjustments in Redis for fast lookup by unified_notification
    if adjustments:
        try:
            from app.core.redis import get_redis_sync
            r = get_redis_sync()
            import json
            r.setex(
                f"notification_tuning:{user_id}",
                86400,  # 24h TTL
                json.dumps(adjustments),
            )
        except Exception as e:
            logger.warning(f"Failed to store notification tuning: {e}")

    return {"user_id": user_id, "adjustments": adjustments, "categories_analyzed": len(rows) if 'rows' in dir() else 0}


def get_tuning_for_category(user_id: str, category: str) -> str:
    """
    Get the current tuning action for a category.

    Returns: "normal", "suppress", "double_cooldown", or "boost"
    """
    try:
        from app.core.redis import get_redis_sync
        import json
        r = get_redis_sync()
        raw = r.get(f"notification_tuning:{user_id}")
        if raw:
            tuning = json.loads(raw)
            entry = tuning.get(category)
            if entry:
                return entry.get("action", "normal")
    except Exception:
        pass
    return "normal"
