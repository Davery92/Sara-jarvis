"""Curiosity Celery tasks (§3.5) — nightly generate + pursue."""
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
    from app.services.curiosity import generate_candidates, select_and_pursue
    sf = get_async_session_factory()
    async with sf() as db:
        gen = await generate_candidates(db, _DAVID)
        pursued = await select_and_pursue(db, _DAVID)
        return {"generate": gen, "pursue": pursued}


@celery_app.task(name="app.tasks.curiosity.run_curiosity")
def run_curiosity():
    """Generate curiosity candidates and pursue the best within budget (§3.5)."""
    return _run_async(_run())
