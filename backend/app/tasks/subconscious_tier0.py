"""Tier 0 subconscious tick — baselines the firehose, promotes only anomalies."""

import asyncio
import logging
import os

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
DEFAULT_USER_ID = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.tasks.subconscious_tier0.tick", bind=True, max_retries=0)
def tick(self):
    """Run one subconscious cycle. Logs promotion_event; escalates only if flag is on."""
    try:
        from app.services.subconscious import run_subconscious_tick
        summary = _run_async(run_subconscious_tick(DEFAULT_USER_ID))
        return summary
    except Exception as e:
        logger.warning(f"[tier0] tick task failed: {e}")


@celery_app.task(name="app.tasks.subconscious_tier0.learn", bind=True, max_retries=0)
def learn(self):
    """Daily: learn promotion thresholds from engagement + decay toward priors."""
    try:
        from app.db.base import SessionLocal
        from app.services.attention_learning import learn_from_recent_engagement, decay_policies
        db = SessionLocal()
        try:
            res = learn_from_recent_engagement(db, DEFAULT_USER_ID, hours=168)
            decayed = decay_policies(db, DEFAULT_USER_ID)
            res["decayed_rows"] = decayed
            logger.info(f"[attention-learning] {res}")
            return res
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[attention-learning] task failed: {e}")
