"""Celery tasks for note maintenance — backfill connections, embeddings, etc."""
import asyncio
import logging
import time

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async function from sync Celery task."""
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
    name="app.tasks.notes.backfill_note_connections",
    bind=True,
    max_retries=0,
    soft_time_limit=1800,
    time_limit=2100,
)
def backfill_note_connections(self, user_id: str):
    """Backfill embeddings and connections for all notes belonging to a user."""
    logger.info(f"Starting note connection backfill for user {user_id}")
    try:
        _run_async(_backfill(user_id))
    except Exception as e:
        logger.error(f"Note backfill failed: {e}", exc_info=True)


async def _backfill(user_id: str):
    from sqlalchemy import text
    from app.db.session import get_async_session_factory
    from app.services.note_connector import process_note_connections

    async_session = get_async_session_factory()

    # Get all notes
    async with async_session() as db:
        result = await db.execute(
            text("""
                SELECT id, title, content, embedding IS NOT NULL as has_embedding
                FROM note
                WHERE user_id = :uid
                ORDER BY created_at ASC
            """),
            {"uid": user_id},
        )
        notes = result.fetchall()

    total = len(notes)
    logger.info(f"Backfill: found {total} notes for user {user_id}")

    processed = 0
    connections_before = 0

    # Get initial connection count
    async with async_session() as db:
        r = await db.execute(
            text("SELECT COUNT(*) FROM note_connection WHERE user_id = :uid"),
            {"uid": user_id},
        )
        connections_before = r.scalar() or 0

    # Process in batches of 10
    batch_size = 10
    for i in range(0, total, batch_size):
        batch = notes[i : i + batch_size]

        for note in batch:
            note_id, title, content, has_embedding = note[0], note[1], note[2], note[3]
            try:
                async with async_session() as db:
                    await process_note_connections(
                        note_id=note_id,
                        user_id=user_id,
                        title=title or "",
                        content=content or "",
                        db=db,
                        generate_embedding=not has_embedding,
                    )
                    await db.commit()
                processed += 1
            except Exception as e:
                logger.warning(f"Backfill: failed for note {note_id}: {e}")

        if processed % 20 == 0 or processed == total:
            logger.info(f"Backfill progress: {processed}/{total} notes processed")

        # Brief pause between batches to avoid overwhelming the embedding service
        if i + batch_size < total:
            await asyncio.sleep(0.5)

    # Final stats
    async with async_session() as db:
        r = await db.execute(
            text("SELECT COUNT(*) FROM note_connection WHERE user_id = :uid"),
            {"uid": user_id},
        )
        connections_after = r.scalar() or 0

    logger.info(
        f"Backfill complete: {processed}/{total} notes processed, "
        f"connections {connections_before} → {connections_after} "
        f"(+{connections_after - connections_before})"
    )
