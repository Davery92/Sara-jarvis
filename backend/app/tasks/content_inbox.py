"""
Celery task for async content extraction in the Content Inbox.
"""
import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.content_inbox.extract_shared_content", bind=True, max_retries=2)
def extract_shared_content(self, content_id: str):
    """Background extraction of shared content."""
    logger.info(f"Starting extraction for shared content: {content_id}")
    try:
        from app.services.content_inbox_service import content_inbox_service

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(content_inbox_service.extract_content(content_id))
        finally:
            loop.close()

        logger.info(f"Extraction complete for: {content_id}")
    except Exception as e:
        logger.error(f"Extraction task failed for {content_id}: {e}")
        raise self.retry(exc=e, countdown=30)
