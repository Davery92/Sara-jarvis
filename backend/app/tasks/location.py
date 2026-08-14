"""Celery tasks for location-triggered reminders and place discovery."""
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


@celery_app.task(name="app.tasks.location.location_trigger_expiry", queue="cognitive")
def location_trigger_expiry():
    """Expire armed one-shot location triggers past their expires_at."""
    from app.db.base import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        try:
            result = db.execute(text("""
                UPDATE location_trigger
                SET status = 'expired'
                WHERE status = 'armed' AND recurring = FALSE
                      AND expires_at IS NOT NULL AND expires_at < NOW()
            """))
            db.commit()
            expired = result.rowcount
        except Exception as e:
            db.rollback()
            logger.error(f"location_trigger_expiry failed: {e}")
            return {"expired": 0, "error": str(e)}

    if expired:
        logger.info(f"Expired {expired} location trigger(s)")
    return {"expired": expired}


@celery_app.task(name="app.tasks.location.place_discovery", queue="cognitive")
def place_discovery():
    """Nightly scan for frequently-visited spots not yet saved as places."""
    from app.db.base import SessionLocal
    from app.services.location_service import discover_and_stage_places

    with SessionLocal() as db:
        try:
            created = _run_async(discover_and_stage_places(db, DEFAULT_USER_ID))
        except Exception as e:
            logger.error(f"place_discovery failed: {e}")
            return {"created": 0, "error": str(e)}

    return {"created": len(created), "places": created}
