"""Prediction-loop Celery tasks (§3.2).

generate_daily  — mint the day's predictions (04:30 ET, internal).
match_pending   — resolve windows as they close (every 15 min); violations → salience.
calibration_report — weekly (§3.9): did stated confidence match reality?
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


async def _with_db(fn):
    from app.db.session import get_async_session_factory
    sf = get_async_session_factory()
    async with sf() as db:
        return await fn(db)


@celery_app.task(name="app.tasks.predictions.generate_daily")
def generate_daily():
    from app.services.prediction_engine import generate_daily_predictions
    return _run_async(_with_db(lambda db: generate_daily_predictions(db, _DAVID)))


@celery_app.task(name="app.tasks.predictions.match_pending")
def match_pending():
    from app.services.prediction_engine import match_pending as _match
    return _run_async(_with_db(lambda db: _match(db, _DAVID)))


@celery_app.task(name="app.tasks.predictions.calibration_report")
def calibration_report():
    from app.services.prediction_engine import compute_calibration
    return _run_async(_with_db(lambda db: compute_calibration(db, _DAVID, 30)))
