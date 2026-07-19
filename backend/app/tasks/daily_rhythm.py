"""Celery task for the nightly Daily Rhythm Engine recompute.

Scheduled via the `scheduled_job` table (key=`recompute-daily-rhythm`) at
3:45 AM ET — after place-discovery (3:30) so leave/return-home observations
reflect the freshest known_place set.
"""
import asyncio
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
SOLO_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.daily_rhythm.recompute_daily_rhythm", queue="cognitive")
def recompute_daily_rhythm():
    """Re-derive every rhythm_key/day_scope pair from location/workout/food/
    calendar/behavioral-pattern history and upsert into `daily_rhythm`."""
    from app.db.base import SessionLocal
    from app.services.daily_rhythm import recompute_daily_rhythm as _recompute, build_rhythm_summary

    with SessionLocal() as db:
        try:
            summary = _run_async(_recompute(db, SOLO_USER_ID))
            rhythm_summary = build_rhythm_summary(db, SOLO_USER_ID)
        except Exception as e:
            db.rollback()
            logger.error(f"recompute_daily_rhythm failed: {e}")
            return {"updated": 0, "error": str(e)}

    # Push the freshly-computed summary into the live snapshot now, rather
    # than waiting for the next cold-start rebuild to pick it up.
    if rhythm_summary:
        try:
            from app.services.context_writer import update_fields
            _run_async(update_fields(SOLO_USER_ID, source="daily_rhythm", rhythm_summary=rhythm_summary))
        except Exception as e:
            logger.warning(f"recompute_daily_rhythm: snapshot push failed: {e}")

    # H3 (Brain Alignment): seed/refresh inferred life facts from the freshly
    # computed rhythm. Idempotent and never overwrites facts David has stated —
    # this is the "weekly re-check of inferred facts" running nightly.
    try:
        from app.services.life_facts import seed_from_rhythm
        from app.db.session import get_async_session_factory

        async def _seed():
            async with get_async_session_factory()() as adb:
                n = await seed_from_rhythm(adb, SOLO_USER_ID)
                await adb.commit()
                return n

        seeded = _run_async(_seed())
        logger.info(f"recompute_daily_rhythm: seeded {seeded} inferred life facts")
    except Exception as e:
        logger.warning(f"recompute_daily_rhythm: life_fact seed failed: {e}")

    logger.info(
        f"recompute_daily_rhythm: {len(summary['updated'])} updated, {len(summary['skipped'])} skipped"
    )
    return summary
