"""
Intelligence monitor Celery tasks.

Handles:
- Periodic source scanning (every 2 hours during waking hours)
- Digest generation (2x daily: noon and 6 PM)
- Breaking news checks (after each scan)
"""

import asyncio
import logging
from datetime import datetime

from app.celery_app import celery_app
from app.core.timezone import now as local_now
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = get_owner_id()


def _get_event_loop():
    """Get or create an event loop for sync->async bridging."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


@celery_app.task(
    name="app.tasks.intelligence.intelligence_scan",
    bind=True,
    queue="low_priority",
    max_retries=1,
)
def intelligence_scan(self):
    """
    Scan all intelligence sources, score, and store new items.
    Runs every 2 hours. Respects waking hours (6 AM - 11 PM).
    """
    hour = local_now().hour
    if hour < 6 or hour >= 23:
        logger.info("Intelligence scan skipped: outside waking hours (6 AM - 11 PM)")
        return {"status": "skipped", "reason": "night_mode"}

    logger.info("Starting intelligence scan")

    try:
        from app.db.session import SessionLocal
        from app.services.intelligence_monitor import intelligence_monitor

        db = SessionLocal()
        try:
            loop = _get_event_loop()
            new_items = loop.run_until_complete(
                intelligence_monitor.scan_all_sources(db)
            )

            # Check for breaking news and send notification if found
            breaking = loop.run_until_complete(
                intelligence_monitor.check_breaking_news(db)
            )

            if breaking:
                logger.info(f"Intelligence scan found {len(breaking)} breaking items")
                _notify_breaking_news(breaking, db)

            return {
                "status": "ok",
                "new_items": len(new_items),
                "breaking_items": len(breaking),
            }
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Intelligence scan failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task(
    name="app.tasks.intelligence.intelligence_digest",
    bind=True,
    queue="cognitive",
    max_retries=1,
)
def intelligence_digest(self):
    """
    Generate an intelligence digest from high-scoring items.
    Runs 2x daily (noon and 6 PM).
    """
    logger.info("Starting intelligence digest generation")

    try:
        from app.db.session import SessionLocal
        from app.services.intelligence_monitor import intelligence_monitor

        db = SessionLocal()
        try:
            loop = _get_event_loop()
            digest = loop.run_until_complete(
                intelligence_monitor.generate_digest(db)
            )

            logger.info(f"Intelligence digest generated: {len(digest)} chars")
            return {
                "status": "ok",
                "digest_length": len(digest),
                "preview": digest[:200],
            }
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Intelligence digest failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def _notify_breaking_news(items: list, db):
    """Send push notification for breaking intelligence items."""
    try:
        from app.services.unified_notification import send_notification

        for item in items[:3]:  # Max 3 notifications per scan
            title = "Intelligence Alert"
            body = item.get("title", "New development detected")
            source = item.get("source", "unknown")

            try:
                loop = _get_event_loop()
                loop.run_until_complete(
                    send_notification(
                        user_id=DEFAULT_USER_ID,
                        title=title,
                        body=f"[{source}] {body}",
                        topic=f"intelligence_{item.get('id', 'unknown')}",
                        db=db,
                    )
                )
            except Exception as e:
                logger.debug(f"Breaking news notification failed: {e}")

    except ImportError:
        logger.debug("Notification service not available for intelligence alerts")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.intelligence.run_predictions", bind=True, max_retries=0)
def run_predictions(self):
    """Run the predictive engine to generate forward-looking suggestions."""
    try:
        from app.services.predictive_engine import send_predictions
        _run_async(send_predictions(DEFAULT_USER_ID))
    except Exception as e:
        logger.warning(f"Predictive engine task failed: {e}")
