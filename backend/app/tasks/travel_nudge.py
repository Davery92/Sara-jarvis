"""Leave-now travel nudge task — checks upcoming events against drive time."""
import asyncio
import logging
import os

from app.celery_app import celery_app
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = get_owner_id()


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.travel_nudge.check_leave_now", bind=True, max_retries=0)
def check_leave_now(self):
    """Check upcoming events with a location against current position + drive time."""
    try:
        from app.services.travel_nudge import check_and_send_leave_now_nudges
        result = _run_async(check_and_send_leave_now_nudges(DEFAULT_USER_ID))
        if result.get("sent"):
            logger.info(f"Leave-now nudges: sent {result['sent']}")
        return result
    except Exception as e:
        logger.warning(f"Leave-now nudge check failed: {e}")
        return {"sent": 0, "error": str(e)}
