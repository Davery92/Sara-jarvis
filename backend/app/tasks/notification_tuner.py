"""Notification tuner task — daily engagement-based frequency adjustment."""

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


@celery_app.task(name="app.tasks.notification_tuner.tune_notifications", bind=True, max_retries=1)
def tune_notifications(self):
    """Compute and apply notification frequency tuning based on engagement."""
    try:
        from app.services.notification_tuner import compute_and_apply_tuning
        result = _run_async(compute_and_apply_tuning(DEFAULT_USER_ID))
        logger.info(f"Notification tuner complete: {result.get('adjustments', {})}")
        return result
    except Exception as e:
        logger.warning(f"Notification tuner failed: {e}")
