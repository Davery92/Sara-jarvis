"""
Celery task that generates the daily morning brief.

Replaces the host-cron `scripts/generate_morning_brief.py` so the schedule
is managed via the `scheduled_job` table (key=`morning-brief-generate`).
"""
import asyncio
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Solo user — only generate for David. Same default as the legacy script.
SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


@celery_app.task(
    name="app.tasks.morning_brief.generate_morning_brief",
    bind=True,
    max_retries=1,
    queue="cognitive",
)
def generate_morning_brief(self):
    """Generate the morning brief and (via the service) send the iOS push."""
    from app.db.base import SessionLocal
    from app.services.morning_brief_service import morning_brief_service

    logger.info("Starting morning brief generation for user %s", SOLO_USER_ID)

    async def _run():
        with SessionLocal() as session:
            brief = await morning_brief_service.generate_brief(SOLO_USER_ID, session)
            return {
                "news_sources": len(brief.news_sources or []),
                "calendar_events": len(brief.calendar_events or []),
                "audio_duration_seconds": brief.audio_duration_seconds,
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        logger.info("Morning brief complete: %s", result)
        return result
    except Exception as e:
        logger.error("Morning brief failed: %s", e)
        # Best-effort error notification — same behavior as the legacy script.
        try:
            from app.services.unified_notification import send_notification
            from app.db.session import get_async_session_factory

            async def _notify():
                AsyncSessionLocal = get_async_session_factory()
                async with AsyncSessionLocal() as async_db:
                    await send_notification(
                        user_id=SOLO_USER_ID,
                        title="Morning brief failed",
                        message=f"Brief generation error: {str(e)[:200]}",
                        priority="important",
                        category="system",
                        source="morning_brief_task",
                        db=async_db,
                    )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_notify())
            finally:
                loop.close()
        except Exception as notify_err:
            logger.error("Failed to send error notification: %s", notify_err)
        raise
