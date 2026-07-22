"""In-process ML training (§4.2.5 / D1 fix) — replaces the phantom job plane.

Nightly, per family: load features/labels → train → cross-validate → write
ml_model_version → promote only if it beats the current model on held-out data.
No Redis job queue, no MinIO artifacts — the model serializes into the DB row.
"""
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


async def _train_all():
    from app.db.session import get_async_session_factory
    from app.services.ml import notification_value
    sf = get_async_session_factory()
    results = {}
    async with sf() as db:
        try:
            results["notification_value"] = await notification_value.train(db, _DAVID)
        except Exception as e:
            logger.warning(f"notification_value training failed: {e}")
            results["notification_value"] = {"effect": "error", "error": str(e)}
    return results


@celery_app.task(name="app.tasks.ml_train.train_all")
def train_all():
    """Nightly retrain of all in-process model families (§4.2.5)."""
    return _run_async(_train_all())
