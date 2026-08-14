"""Judge beat task (SARA_MIND_V2 Phase 4/§3.6). Shadow mode — see
app/services/judge.py's module docstring: real decisions + prep dispatch,
no live delivery wiring yet. Runs on a short interval rather than the
plan's event-driven triggers (candidate arrival / slot boundaries / seams)
since those hooks don't exist yet either; `run_judge()` is a cheap no-op
when there are no pending candidates (only appraisal.py creates any today,
gated by its own ambient-skip check), so a tight interval costs nothing.
"""
import asyncio
import logging

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()


@celery_app.task(
    name="app.tasks.judge.run_judge_cycle",
    queue="cognitive",
)
def run_judge_cycle():
    try:
        return asyncio.run(_run_async())
    except Exception as e:
        logger.error(f"[judge] cycle task failed: {e}")
        raise


async def _run_async():
    from app.services.judge import run_judge

    result = await run_judge(DEFAULT_USER_ID)
    logger.info(f"[judge] beat cycle result: {result}")
    return result
