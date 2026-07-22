"""Dream-cycle Celery task (§3.8) — mid-sleep, offline."""
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
    from app.services.dreams import run_dream_cycle
    sf = get_async_session_factory()
    async with sf() as db:
        return await run_dream_cycle(db)


@celery_app.task(name="app.tasks.dreams.run_dream_cycle")
def run_dream_cycle():
    return _run_async(_run())
