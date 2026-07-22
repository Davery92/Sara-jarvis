"""Belief promotion sweep (§3.3 / D2) — daily, after pattern mining."""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _run():
    from app.db.session import get_async_session_factory
    from app.services.belief_promotion import run_promotion
    sf = get_async_session_factory()
    async with sf() as db:
        return await run_promotion(db, _DAVID)


@celery_app.task(name="app.tasks.belief_promotion.run_promotion")
def run_promotion():
    return _run_async(_run())
