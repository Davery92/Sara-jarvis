"""Calendar prep task — checks upcoming events and sends prep notifications."""

import asyncio
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.calendar_prep.check_upcoming", bind=True, max_retries=0)
def check_upcoming(self):
    """Check for upcoming events and send prep notifications."""
    try:
        from app.services.calendar_prep import check_and_send_preps
        _run_async(check_and_send_preps(DEFAULT_USER_ID))
    except Exception as e:
        logger.warning(f"Calendar prep check failed: {e}")


@celery_app.task(name="app.tasks.calendar_prep.cross_system_check", bind=True, max_retries=0)
def cross_system_check(self):
    """Cross-reference email, calendar, notes for insights."""
    try:
        from app.services.proactive_intelligence import cross_reference_check
        from app.services.unified_notification import send_notification

        insights = _run_async(cross_reference_check(DEFAULT_USER_ID))
        for insight in insights:
            _run_async(send_notification(
                user_id=DEFAULT_USER_ID,
                title=insight["title"],
                message=insight["message"],
                priority=insight.get("priority", "normal"),
                category="checkin",
                topic=f"xref:{hash(insight['title']) % 100000}",
                source="cross_system_synthesis",
            ))
        if insights:
            logger.info(f"Cross-system synthesis: sent {len(insights)} insight(s)")
    except Exception as e:
        logger.warning(f"Cross-system synthesis failed: {e}")
