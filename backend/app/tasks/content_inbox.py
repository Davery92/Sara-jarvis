"""
Celery task for async content extraction in the Content Inbox.
"""
import asyncio
import logging
from datetime import datetime

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.content_inbox.extract_shared_content", bind=True, max_retries=2)
def extract_shared_content(self, content_id: str):
    """Background extraction of shared content."""
    logger.info(f"Starting extraction for shared content: {content_id}")
    try:
        from app.services.content_inbox_service import content_inbox_service

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(content_inbox_service.extract_content(content_id))
        finally:
            loop.close()

        logger.info(f"Extraction complete for: {content_id}")
    except Exception as e:
        logger.error(f"Extraction task failed for {content_id}: {e}")
        raise self.retry(exc=e, countdown=30)


@celery_app.task(name="app.tasks.content_inbox.send_morning_inbox_digest")
def send_morning_inbox_digest():
    """
    Send a daily morning push notification when Inbox has unread backlog.

    Includes both:
    - Content inbox unread items
    - Attention queue unread items (new/sent)
    """
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.services.unified_notification import send_notification

    async def _run() -> dict:
        db = SessionLocal()
        try:
            today = local_now().strftime("%Y-%m-%d")

            # Only users with active push tokens are candidates.
            user_rows = db.execute(text("""
                SELECT DISTINCT user_id
                FROM push_token
                WHERE is_active = TRUE
            """)).fetchall()

            users_notified = 0
            users_skipped = 0

            for row in user_rows:
                user_id = row[0]

                content_unread_row = db.execute(text("""
                    SELECT COUNT(*)::int AS unread_count
                    FROM shared_content
                    WHERE user_id = :user_id
                      AND status = 'unread'
                """), {"user_id": user_id}).fetchone()
                content_unread = int(content_unread_row.unread_count if content_unread_row else 0)

                try:
                    attention_unread_row = db.execute(text("""
                        SELECT COUNT(*)::int AS unread_count
                        FROM outbox_item
                        WHERE user_id = :user_id
                          AND status IN ('new', 'sent')
                    """), {"user_id": user_id}).fetchone()
                    attention_unread = int(attention_unread_row.unread_count if attention_unread_row else 0)
                except Exception:
                    attention_unread = 0

                total_unread = content_unread + attention_unread
                if total_unread <= 0:
                    users_skipped += 1
                    continue

                latest_row = db.execute(text("""
                    SELECT title, content_type
                    FROM shared_content
                    WHERE user_id = :user_id
                      AND status = 'unread'
                    ORDER BY shared_at DESC
                    LIMIT 1
                """), {"user_id": user_id}).fetchone()

                top_attention = None
                if attention_unread > 0:
                    try:
                        top_attention = db.execute(text("""
                            SELECT title, category, priority
                            FROM outbox_item
                            WHERE user_id = :user_id
                              AND status IN ('new', 'sent')
                            ORDER BY
                                CASE priority
                                    WHEN 'critical' THEN 0
                                    WHEN 'urgent' THEN 1
                                    WHEN 'high' THEN 2
                                    WHEN 'normal' THEN 3
                                    ELSE 4
                                END,
                                created_at DESC
                            LIMIT 1
                        """), {"user_id": user_id}).fetchone()
                    except Exception:
                        top_attention = None

                latest_title = (latest_row.title if latest_row else None) or "new content"
                latest_type = (latest_row.content_type if latest_row else None) or "item"

                item_word = "item" if total_unread == 1 else "items"
                title = f"Morning inbox brief: {total_unread} unread {item_word}"

                body_parts = []
                if attention_unread > 0:
                    if top_attention:
                        body_parts.append(
                            f"Attention: {attention_unread} unread (top: {top_attention.title})."
                        )
                    else:
                        body_parts.append(f"Attention: {attention_unread} unread.")
                if content_unread > 0:
                    body_parts.append(
                        f"Content: {content_unread} unread. Latest: {latest_title} ({latest_type})."
                    )
                body_parts.append("Open Inbox to triage.")
                body = " ".join(body_parts)
                digest_source = "attention_digest" if attention_unread > 0 else "inbox_digest"

                result = await send_notification(
                    user_id=user_id,
                    title=title,
                    message=body,
                    priority="normal",
                    topic=f"inbox:morning_digest:{today}",
                    category="general",
                    source=digest_source,
                    cooldown_hours=24.0,
                    db=db,
                    # The morning digest is itself a summary OF the attention queue,
                    # so it must not be re-routed back into the queue. Force a real push.
                    _bypass_attention=True,
                )

                # send_notification doesn't commit a caller-supplied session
                # (see mindv2_deliver.py's identical fix, 2026-07-30) — without
                # this the notification_log row silently rolled back, which
                # for this job also meant the 24h cooldown dedup could never
                # see a prior send and the digest could re-fire same-day.
                db.commit()

                if result.get("sent"):
                    users_notified += 1
                else:
                    users_skipped += 1

            return {
                "users_seen": len(user_rows),
                "users_notified": users_notified,
                "users_skipped": users_skipped,
            }
        finally:
            db.close()

    try:
        result = asyncio.run(_run())
        logger.info(f"Morning inbox digest complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Morning inbox digest failed: {e}")
        raise
