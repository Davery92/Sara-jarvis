"""Narrator Celery tasks.

- `sweep_triggers` — fires every registered Trigger once (PR 2 / PR 5)
- `daily_patch_notes` — fake release notes for the last 24h (PR 7)
- `weekly_recap` — fake release notes for the last 7 days (PR 7)
- `sponsored_interjection` — absurdist non-sequitur (PR 7)

All run on the DB-backed Celery beat (ScheduledJob rows seeded by
migrations 067 and 069).
"""
from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.db.session import get_async_session_factory
from app.services.unified_notification import DAVID_USER_ID
from app.tasks.autonomy import _run_async  # reuse the asyncio loop runner

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.narrator.sweep_triggers",
    bind=True,
    queue="cognitive",
    max_retries=0,
)
def sweep_triggers(self):
    """Periodic — run all registered narrator triggers once for David."""
    try:
        return _run_async(_sweep_async())
    except Exception as exc:
        logger.error("narrator: sweep failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


async def _sweep_async() -> dict:
    # Import inside the task so trigger modules are imported on the
    # Celery worker (triggers self-register at import time).
    from app.services.narrator.coordinator import sweep_all

    async_session = get_async_session_factory()
    async with async_session() as db:
        results = await sweep_all(db, DAVID_USER_ID)

    emitted = [r for r in results if r["status"] == "emitted"]
    cooled = [r for r in results if r["status"] == "cooldown"]
    errored = [r for r in results if r["status"] == "error"]

    logger.info(
        "narrator sweep: %d trigger(s) checked, %d emitted, %d cooled, %d errored",
        len(results),
        len(emitted),
        len(cooled),
        len(errored),
    )
    return {
        "status": "ok",
        "checked": len(results),
        "emitted": len(emitted),
        "cooled": len(cooled),
        "errored": len(errored),
        "results": results,
    }


# ── Scheduled broadcasts (PR 7) ──────────────────────────────────────────────


@celery_app.task(
    name="app.tasks.narrator.daily_patch_notes",
    bind=True,
    queue="cognitive",
    max_retries=0,
)
def daily_patch_notes(self):
    """Daily patch-notes broadcast — fires once a day, 7am ET."""
    try:
        return _run_async(_scheduled_async("daily_patch_notes"))
    except Exception as exc:
        logger.error("narrator: daily_patch_notes failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


@celery_app.task(
    name="app.tasks.narrator.weekly_recap",
    bind=True,
    queue="cognitive",
    max_retries=0,
)
def weekly_recap(self):
    """Weekly recap broadcast — fires Sunday 6pm ET."""
    try:
        return _run_async(_scheduled_async("weekly_recap"))
    except Exception as exc:
        logger.error("narrator: weekly_recap failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


@celery_app.task(
    name="app.tasks.narrator.sponsored_interjection",
    bind=True,
    queue="cognitive",
    max_retries=0,
)
def sponsored_interjection(self):
    """Absurdist non-sequitur. Runs every ~3 days; the beat handles cadence."""
    try:
        return _run_async(_scheduled_async("sponsored_interjection"))
    except Exception as exc:
        logger.error("narrator: sponsored_interjection failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


async def _scheduled_async(kind: str) -> dict:
    from app.services.narrator.scheduled import run_scheduled

    async_session = get_async_session_factory()
    async with async_session() as db:
        result = await run_scheduled(kind, DAVID_USER_ID, db)
    logger.info("narrator: scheduled %s → %s", kind, result.get("status"))
    return result
