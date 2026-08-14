"""Appraisal loop beat task (SARA_MIND_V2 Phase 3, §3.4/§4).

Dark/additive: runs alongside deliberation.py, does not replace it.
`run_appraisal()` writes World Brief patches + say_candidates; nothing
downstream reads say_candidate for real delivery yet (Phase 2/4 territory),
so this task cannot change what David sees today. Interval matches the
plan's "60-120s debounce, or immediately for security/interoception" loosely
— set conservatively at 3 min since the cheap ambient-skip gate already
keeps most cycles from calling the LLM at all.
"""

import asyncio
import logging

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()


@celery_app.task(
    name="app.tasks.appraisal.run_appraisal_cycle",
    queue="cognitive",
)
def run_appraisal_cycle():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[appraisal] cycle task failed: {e}")
        raise


async def _run_async():
    from app.services.appraisal import run_appraisal

    result = await run_appraisal(DEFAULT_USER_ID)
    logger.info(f"[appraisal] beat cycle result: {result}")
    return result
