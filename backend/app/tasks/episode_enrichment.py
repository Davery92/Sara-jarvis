"""Debounced, incremental episode enrichment (chat harness repair Phase 6).

`schedule_conversation_enrichment` is called from the chat turn instead of
the old `asyncio.create_task(_enrich_episodes_batch(...))`. It sets a
short-TTL Redis key per conversation as the "a job is already pending"
uniqueness marker, then schedules the Celery task after an idle debounce. A
second turn landing inside that debounce window finds the key already set
and schedules nothing — its new episode is simply included when the already
-scheduled task runs (coalescing), because the actual selection of which
episodes to enrich happens at task run time via the watermark, not at
schedule time.
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

IDLE_DEBOUNCE_SECONDS = 45
SCHEDULE_LOCK_TTL = IDLE_DEBOUNCE_SECONDS + 15
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 20  # seconds; exponential: 20, 40, 80, 160, 320


def schedule_conversation_enrichment(conversation_id: str, user_id: str) -> None:
    """Fire-and-forget scheduler. Never raises into the chat response path."""
    if not conversation_id:
        return
    try:
        from app.core.redis import get_redis_sync

        lock_key = f"enrich:sched:{conversation_id}"
        r = get_redis_sync()
        if not r.set(lock_key, "1", nx=True, ex=SCHEDULE_LOCK_TTL):
            logger.debug(f"Enrichment already scheduled for conversation {conversation_id}; coalescing")
            return

        enrich_conversation_task.apply_async(
            args=[conversation_id, user_id],
            countdown=IDLE_DEBOUNCE_SECONDS,
        )
    except Exception as e:
        # Scheduling is best-effort; a missed enrichment run is not
        # response-critical and must never break the chat turn.
        logger.debug(f"Failed to schedule enrichment for conversation {conversation_id}: {e}")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    name="app.tasks.episode_enrichment.enrich_conversation",
    bind=True,
    max_retries=MAX_RETRIES,
    queue="cognitive",
)
def enrich_conversation_task(self, conversation_id: str, user_id: str):
    from app.db.base import SessionLocal
    from app.services.episode_enrichment import enrich_conversation_incremental

    db = SessionLocal()
    try:
        result = _run_async(enrich_conversation_incremental(db, conversation_id, user_id))

        if result["status"] != "error":
            return result

        attempt = self.request.retries
        if attempt >= MAX_RETRIES:
            _record_terminal_failure(db, conversation_id, result["reason"])
            logger.error(
                f"Episode enrichment permanently failed for conversation "
                f"{conversation_id} after {attempt} retries: {result['reason']}"
            )
            return result

        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
        raise self.retry(countdown=backoff, exc=RuntimeError(result["reason"]))
    finally:
        db.close()


def _record_terminal_failure(db, conversation_id: str, reason: str) -> None:
    try:
        from app.models.conversation import Conversation

        convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if convo is None:
            return
        convo.enrichment_status = "failed"
        convo.enrichment_attempts = (convo.enrichment_attempts or 0) + 1
        convo.enrichment_last_error = (reason or "")[:2000]
        convo.enrichment_updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to record terminal enrichment failure for {conversation_id}: {e}")
        db.rollback()
