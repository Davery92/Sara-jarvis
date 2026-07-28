"""Weekly review beat task (SARA_MIND_V2 Phase 4, §6). Sunday evening,
staggered from the existing weekly jobs (self-audit 18:30, learning digest
19:00) to avoid piling three weekly LLM-adjacent jobs into one slot.
"""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@celery_app.task(
    name="app.tasks.mindv2_weekly_review.run_weekly_review_task",
    queue="cognitive",
)
def run_weekly_review_task():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[mindv2_weekly_review] task failed: {e}")
        raise


async def _run_async():
    from app.services.mindv2_weekly_review import run_weekly_review

    result = await run_weekly_review(DEFAULT_USER_ID)
    logger.info(f"[mindv2_weekly_review] result: {result}")
    return result
