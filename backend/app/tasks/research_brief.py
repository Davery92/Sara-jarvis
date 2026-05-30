"""Nightly research brief Celery task.

Scheduled via the `scheduled_job` table (key=`research-brief-generate`) at 2 AM ET.
"""
import asyncio
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


@celery_app.task(
    name="app.tasks.research_brief.generate_research_brief",
    bind=True,
    max_retries=1,
    queue="cognitive",
    # Reliability: ack only after completion so a dropped/crashed worker
    # triggers broker redelivery instead of silently losing the task (as
    # happened in the 2 AM dispatch burst). Upsert-by-(user,date) makes
    # redelivery idempotent. Time limits backstop a hung LLM/TTS call.
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=900,
    time_limit=1080,
)
def generate_research_brief(self):
    """Fetch research feeds, synthesize the long-form brief, and render audio."""
    from app.db.base import SessionLocal
    from app.services.research_brief.brief_service import research_brief_service

    logger.info("Starting research brief generation for user %s", SOLO_USER_ID)

    async def _run():
        with SessionLocal() as session:
            brief = await research_brief_service.generate(SOLO_USER_ID, session)
            return {
                "paper_count": brief.paper_count,
                "audio_duration_seconds": brief.audio_duration_seconds,
                "has_audio": bool(brief.audio_path),
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        logger.info("Research brief complete: %s", result)
        return result
    except Exception as e:
        logger.error("Research brief failed: %s", e)
        try:
            from app.services.unified_notification import send_notification
            from app.db.session import get_async_session_factory

            async def _notify():
                AsyncSessionLocal = get_async_session_factory()
                async with AsyncSessionLocal() as async_db:
                    await send_notification(
                        user_id=SOLO_USER_ID,
                        title="Research brief failed",
                        message=f"Brief generation error: {str(e)[:200]}",
                        priority="important",
                        category="system",
                        source="research_brief_task",
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
