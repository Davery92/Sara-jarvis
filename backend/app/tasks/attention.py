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

# Per-category escalation cooldowns (hours). If we've already pushed a
# similar item in this window, swallow the escalation and just mark the
# item 'sent'. Prevents the "same Jim email, different hash" loop where
# cross_system_check kept minting fresh attention items with drifting
# topics and the escalator dutifully pushed each one.
_ESCALATION_COOLDOWN_HOURS = {
    "checkin": 24.0,       # informational cross-refs — once per day is plenty
    "acs_discovery": 12.0,
    "email": 4.0,
    "calendar_prep": 2.0,
}
_DEFAULT_ESCALATION_COOLDOWN_HOURS = 6.0

# Categories that should never escalate to a push. They live in the
# attention queue but David reads them in the webapp, not on his phone.
#
# calendar_prep is time-relative: its body is frozen at creation time
# ("starts in 36 minutes") from a 35-55 min pre-event window. Escalation only
# fires after ESCALATION_HOURS (2h) of no reads, which is always *longer* than
# that window — so an escalated calendar prep is guaranteed to land after the
# event has already started/ended, pushing stale "starts in N minutes" text
# ("it's already over"). Never escalate it; a prep reminder is worthless once
# the event has passed. (Timely delivery happens at creation, not here.)
_NO_ESCALATE_CATEGORIES: set[str] = {"calendar_prep"}


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
        archived_confirmations = db.execute(text("""
            UPDATE autonomy_attention_item
            SET status = 'archived', archived_at = NOW(), updated_at = NOW()
            WHERE status = 'new'
              AND payload->>'prediction_grade' = 'confirmation'
            RETURNING id
        """)).fetchall()
        if archived_confirmations:
            db.commit()

        # Pull every still-new item older than the threshold across all users.
        rows = db.execute(text("""
            SELECT id::text, user_id, title, body, category, priority, source,
                   dedupe_key, created_at, payload
            FROM autonomy_attention_item
            WHERE status = 'new'
              AND COALESCE(payload->>'prediction_grade', '') != 'confirmation'
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
            return {
                "checked_at": local_now().isoformat(),
                "archived_confirmations": len(archived_confirmations),
                "escalated": 0,
            }

        per_user_count: dict[str, int] = {}
        escalated_ids: list[str] = []
        push_attempts = 0
        push_successes = 0

        for row in rows:
            user_id = row.user_id
            if per_user_count.get(user_id, 0) >= MAX_ESCALATIONS_PER_USER:
                continue

            category = row.category or "general"
            topic = row.dedupe_key or f"attention_escalation:{row.id}"

            # Some categories never escalate — they live in the queue and the
            # user picks them up in the webapp.
            if category in _NO_ESCALATE_CATEGORIES:
                escalated_ids.append(row.id)
                continue

            # Recent-push guard. If a similar item (same topic OR same
            # title/body fingerprint) was pushed within this category's
            # escalation cooldown, skip. This is the fix for the "Jim email
            # every hour" bug: cross_system_check was minting new attention
            # items with drifting hash-based topics, and the old escalator
            # dutifully pushed every single one because cooldown_hours=0.
            cooldown_h = _ESCALATION_COOLDOWN_HOURS.get(
                category, _DEFAULT_ESCALATION_COOLDOWN_HOURS
            )
            try:
                recent = db.execute(text("""
                    SELECT 1 FROM notification_log
                    WHERE user_id = :uid
                      AND sent = TRUE
                      AND sent_at > NOW() - MAKE_INTERVAL(secs => :age_secs)
                      AND (
                          topic = :topic
                          OR (category = :category AND title = :title)
                      )
                    LIMIT 1
                """), {
                    "uid": user_id,
                    "age_secs": int(cooldown_h * 3600),
                    "topic": topic,
                    "category": category,
                    "title": row.title,
                }).fetchone()
                if recent:
                    logger.info(
                        f"Attention escalation suppressed by recent push: "
                        f"item={row.id} topic={topic} category={category} "
                        f"cooldown={cooldown_h}h"
                    )
                    escalated_ids.append(row.id)
                    continue
            except Exception as e:
                # If the guard query fails, fall through to the normal path —
                # we'd rather occasionally double-notify than block everything.
                logger.warning(f"Escalation cooldown check failed: {e}")

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
                    topic=topic,
                    category=category,
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
            "archived_confirmations": len(archived_confirmations),
            "candidates": len(rows),
            "push_attempts": push_attempts,
            "push_successes": push_successes,
            "escalated": len(escalated_ids),
            "users": len(per_user_count),
        }
    finally:
        # Explicitly end the transaction before returning the connection to the
        # pool. Every read here (the SELECTs, and the early "no rows" return
        # path) opens an implicit transaction; without this rollback the sync
        # connection goes back to the pool INTRANS and the NEXT run of this
        # 30-min task fails at checkout with "can't change 'autocommit' now:
        # connection in transaction status INTRANS" — a self-poisoning loop.
        try:
            db.rollback()
        except Exception:
            pass
        db.close()
