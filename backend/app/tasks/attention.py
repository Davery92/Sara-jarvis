"""
Attention queue Celery tasks.

These tasks make sure attention items don't sit unread forever when David
isn't actively viewing the webapp:

- ``escalate_unread_attention``: every 30 minutes, find ``status='new'``
  items older than ESCALATION_HOURS and push them out as real notifications,
  then mark them ``status='sent'`` so they aren't pushed again.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import text

from app.celery_app import celery_app
from app.core.timezone import now as local_now
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# How long an attention item can sit unread before we escalate it to a push.
ESCALATION_HOURS = 2.0

# Hard ceiling on how many items we'll escalate per user per sweep, to avoid
# blasting the phone with a dozen pushes if many items piled up at once.
MAX_ESCALATIONS_PER_USER = 5


@celery_app.task(
    name="app.tasks.attention.escalate_unread_attention",
    queue="cognitive",
)
def escalate_unread_attention():
    """Push attention items that have been sitting unread too long."""
    try:
        return asyncio.run(_escalate_unread_attention_async())
    except Exception as e:
        logger.error(f"Attention escalation sweep failed: {e}")
        raise


async def _escalate_unread_attention_async() -> dict:
    from app.services.unified_notification import send_notification

    db = SessionLocal()
    try:
        # Pull every still-new item older than the threshold across all users.
        rows = db.execute(text("""
            SELECT id::text, user_id, title, body, category, priority, source,
                   dedupe_key, created_at
            FROM autonomy_attention_item
            WHERE status = 'new'
              AND created_at < NOW() - MAKE_INTERVAL(secs => :age_secs)
            ORDER BY user_id,
                     CASE priority
                         WHEN 'critical' THEN 0
                         WHEN 'urgent' THEN 1
                         WHEN 'high' THEN 2
                         WHEN 'normal' THEN 3
                         ELSE 4
                     END,
                     created_at ASC
        """), {"age_secs": int(ESCALATION_HOURS * 3600)}).fetchall()

        if not rows:
            return {"checked_at": local_now().isoformat(), "escalated": 0}

        per_user_count: dict[str, int] = {}
        escalated_ids: list[str] = []
        push_attempts = 0
        push_successes = 0

        for row in rows:
            user_id = row.user_id
            if per_user_count.get(user_id, 0) >= MAX_ESCALATIONS_PER_USER:
                continue
            per_user_count[user_id] = per_user_count.get(user_id, 0) + 1

            push_attempts += 1
            try:
                result = await send_notification(
                    user_id=user_id,
                    title=row.title,
                    message=row.body or "",
                    # Bump escalated items to "high" so they actually leave as a
                    # push regardless of the per-category cooldown floor.
                    priority="high",
                    topic=row.dedupe_key or f"attention_escalation:{row.id}",
                    category=row.category or "general",
                    source="attention_escalation",
                    cooldown_hours=0,
                    db=db,
                    _bypass_attention=True,
                    _attention_item_id=row.id,
                )
                if result.get("sent"):
                    push_successes += 1
                    escalated_ids.append(row.id)
                else:
                    logger.info(
                        f"Attention escalation suppressed for {row.id}: "
                        f"reason={result.get('reason')}"
                    )
                    # Even if dedup blocked the push, mark the item sent so we
                    # don't try again every 30 minutes forever.
                    escalated_ids.append(row.id)
            except Exception as e:
                logger.warning(f"Failed to escalate attention item {row.id}: {e}")

        if escalated_ids:
            db.execute(text("""
                UPDATE autonomy_attention_item
                SET status = 'sent', updated_at = NOW()
                WHERE id = ANY(CAST(:ids AS uuid[]))
            """), {"ids": escalated_ids})
            db.commit()

        return {
            "checked_at": local_now().isoformat(),
            "candidates": len(rows),
            "push_attempts": push_attempts,
            "push_successes": push_successes,
            "escalated": len(escalated_ids),
            "users": len(per_user_count),
        }
    finally:
        db.close()
