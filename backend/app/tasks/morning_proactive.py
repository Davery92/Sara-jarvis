"""
Celery task for the morning proactive behavioral-pattern check.

morning_proactive_service.py was fully built (pattern trigger evaluation, LLM
message crafting, send via the gated unified_notification pipeline, response
recording) but had no scheduler entry point anywhere in the codebase — so
`behavioral_pattern.times_suggested/accepted/rejected` stayed at 0 for all
rows and the pattern -> standing_order promotion pipeline (which requires
status='confirmed', set by record_response) never activated. This task is
the missing entry point, scheduled via the `scheduled_job` table like the
other morning-* tasks (key=`morning-proactive-check`).
"""
import asyncio
import logging
import os

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

SOLO_USER_ID = get_owner_id()


@celery_app.task(
    name="app.tasks.morning_proactive.run_check",
    bind=True,
    max_retries=1,
    queue="cognitive",
)
def run_check(self):
    """Evaluate active behavioral patterns and send any triggered suggestions."""
    from app.db.base import SessionLocal
    from app.services.morning_proactive_service import run_morning_proactive_check

    logger.info("Starting morning proactive check for user %s", SOLO_USER_ID)

    async def _run():
        with SessionLocal() as session:
            return await run_morning_proactive_check(session, SOLO_USER_ID)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        logger.info("Morning proactive check complete: %s", result)
        return result
    except Exception as e:
        logger.warning(f"Morning proactive check failed: {e}")
        raise self.retry(exc=e, countdown=300)
