"""World Brief maintainer sweep (SARA_MIND_V2 Phase 1, §3.1/§4.13).

Temporary — this is the "5-min sweep translating existing signals into
patches" the plan describes as pre-appraisal-loop scaffolding; its query
logic becomes the appraisal loop's tool layer in Phase 3
(`app/services/appraisal.py`), at which point this task is retired.

Runs unconditionally (not gated behind MINDV2_BRIEF) so the brief stays
warm and comparable during the Phase 2 dark/overlap window even before
chat consumes it — D3's cutover discipline needs real data to judge
against, not a cold table flipped on for the first time at cutover.
"""

import asyncio
import logging

from app.celery_app import celery_app
from app.db.session import get_async_session_factory

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@celery_app.task(
    name="app.tasks.world_brief.sweep_world_brief",
    queue="cognitive",
)
def sweep_world_brief():
    """Refresh the World Brief's patch-backed sections from live sources."""
    try:
        return asyncio.run(_sweep_async())
    except Exception as e:
        logger.error(f"[world_brief] sweep task failed: {e}")
        raise


async def _sweep_async():
    from app.services.world_brief import sweep_brief

    factory = get_async_session_factory()
    async with factory() as db:
        stats = await sweep_brief(db, DEFAULT_USER_ID)
        logger.info(f"[world_brief] sweep complete: {stats}")
        return stats


@celery_app.task(
    name="app.tasks.world_brief.purge_say_candidates",
    queue="cognitive",
)
def purge_say_candidates():
    """SARA_MIND_V2 §3.5 mechanical TTL guarantee. Dark (no candidates
    exist yet — see app/services/say_candidate.py) but runs unconditionally
    so the purge path is exercised and provable before Phase 2 wires a
    single sender to create_candidate()."""
    try:
        return asyncio.run(_purge_async())
    except Exception as e:
        logger.error(f"[say_candidate] purge task failed: {e}")
        raise


async def _purge_async():
    from app.services.say_candidate import purge_expired

    factory = get_async_session_factory()
    async with factory() as db:
        n = await purge_expired(db, DEFAULT_USER_ID)
        if n:
            logger.info(f"[say_candidate] purged {n} expired candidate(s)")
        return {"purged": n}
