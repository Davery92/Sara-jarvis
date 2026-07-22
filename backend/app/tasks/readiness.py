"""Readiness compute Celery task (§6.2)."""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


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
    from app.services.readiness_engine import compute_readiness
    sf = get_async_session_factory()
    async with sf() as db:
        return await compute_readiness(db)


@celery_app.task(name="app.tasks.readiness.compute")
def compute():
    return _run_async(_run())
