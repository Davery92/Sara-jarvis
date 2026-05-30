"""
Celery wrappers for what used to be in-process background schedulers in
main_simple.py and the daily_brief module:

* daily_brief.scheduler.DailyBriefScheduler  → 4 tasks (consolidate, context update, archive, weekly synthesis)
* nightly_dream_service.start_dream_scheduler → 1 task (nightly dream cycle, 2 AM)
* main_simple.NotificationScheduler          → 1 task (5s timer/reminder pre-dispatch)

These all live in `scheduled_job` so they can be edited from the settings UI.
"""
import asyncio
import logging
from datetime import datetime, timezone as dt_tz, timedelta
from typing import Any, List, Tuple

import pytz

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
EASTERN = pytz.timezone("America/New_York")


def _run_async(coro):
    """Helper: run an async coroutine from a sync Celery task body."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── daily_brief scheduler tasks ────────────────────────────────────
def _all_brief_user_ids() -> List[str]:
    from pathlib import Path
    briefs_dir = Path("/home/david/jarvis/data/briefs")
    if not briefs_dir.exists():
        return []
    return [p.name for p in briefs_dir.iterdir() if p.is_dir()]


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_consolidate", queue="cognitive")
def daily_brief_consolidate():
    """Hourly day-layer consolidation. Skips outside 8 AM–11 PM Eastern."""
    now_et = datetime.now(EASTERN)
    if not (8 <= now_et.hour < 23):
        logger.debug("daily_brief_consolidate: outside active hours, skipping")
        return {"skipped": "inactive_hours"}

    from app.services.daily_brief.day_layer import day_layer

    async def _run():
        ran = 0
        for user_id in _all_brief_user_ids():
            try:
                if day_layer.needs_consolidation(user_id):
                    await day_layer.consolidate(user_id)
                    ran += 1
            except Exception as e:
                logger.error("daily_brief consolidate failed for %s: %s", user_id[:8], e)
        return {"users_consolidated": ran}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_context_update", queue="cognitive")
def daily_brief_context_update():
    """Daily 11 PM context-layer update."""
    from app.services.daily_brief.day_layer import day_layer
    from app.services.daily_brief.context_layer import context_layer

    async def _run():
        updated = 0
        for user_id in _all_brief_user_ids():
            try:
                day_content = day_layer.read(user_id)
                if day_content:
                    await context_layer.daily_update(user_id, day_content)
                    updated += 1
            except Exception as e:
                logger.error("daily_brief context update failed for %s: %s", user_id[:8], e)
        return {"users_updated": updated}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_archive", queue="maintenance")
def daily_brief_archive():
    """Midnight day-layer archival."""
    from app.services.daily_brief.day_layer import day_layer
    from app.services.daily_brief.archiver import archiver

    async def _run():
        archived = 0
        for user_id in _all_brief_user_ids():
            try:
                content = day_layer.read(user_id)
                if content:
                    await archiver.archive_day_layer(user_id, content)
                    day_layer.clear(user_id)
                    archived += 1
            except Exception as e:
                logger.error("daily_brief archive failed for %s: %s", user_id[:8], e)
        return {"users_archived": archived}

    return _run_async(_run())


@celery_app.task(name="app.tasks.inproc_schedulers.daily_brief_weekly_synthesis", queue="cognitive")
def daily_brief_weekly_synthesis():
    """Sunday 3 AM weekly stable-layer synthesis."""
    from app.db.base import SessionLocal
    from app.services.daily_brief.stable_layer import stable_layer

    async def _run():
        synthesized = 0
        for user_id in _all_brief_user_ids():
            db = SessionLocal()
            try:
                await stable_layer.weekly_synthesis(user_id, db)
                synthesized += 1
            except Exception as e:
                logger.error("weekly synthesis failed for %s: %s", user_id[:8], e)
            finally:
                db.close()
        return {"users_synthesized": synthesized}

    return _run_async(_run())


# ── Nightly dream cycle ────────────────────────────────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.nightly_dream_cycle", queue="cognitive")
def nightly_dream_cycle():
    """Nightly memory consolidation 'dream' cycle. Cron-scheduled at 2 AM ET."""
    from app.services.nightly_dream_service import nightly_dream_service

    async def _run():
        # _run_nightly_dream_cycle is a no-op if already dreaming.
        await nightly_dream_service._run_nightly_dream_cycle()
        return {"ok": True}

    return _run_async(_run())


# ── Notification pre-dispatch (timers + reminders) ─────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.notification_predispatch", queue="critical")
def notification_predispatch():
    """
    Find timers/reminders firing in the next ~20 seconds and dispatch their
    push notifications. Replaces main_simple.NotificationScheduler's 5s loop.
    """
    from app.db.base import SessionLocal
    from app.models.reminder import Timer, Reminder

    async def _run():
        now = datetime.now(dt_tz.utc)
        cutoff = now + timedelta(seconds=20)
        sent = 0
        with SessionLocal() as db:
            # Timers due in the window
            timers = db.query(Timer).filter(Timer.is_active.is_(True)).all()
            for t in timers:
                end = t.end_time
                if end.tzinfo is None:
                    end = end.replace(tzinfo=dt_tz.utc)
                if now <= end <= cutoff:
                    try:
                        await _dispatch_timer(t)
                        sent += 1
                    except Exception as e:
                        logger.error("timer dispatch failed for %s: %s", t.id, e)

            # Reminders due in the window
            reminders = db.query(Reminder).filter(Reminder.is_completed.is_(False)).all()
            for r in reminders:
                rt = r.reminder_time
                if rt.tzinfo is None:
                    rt = rt.replace(tzinfo=dt_tz.utc)
                if now <= rt <= cutoff:
                    try:
                        await _dispatch_reminder(r)
                        sent += 1
                    except Exception as e:
                        logger.error("reminder dispatch failed for %s: %s", r.id, e)

        return {"sent": sent}

    return _run_async(_run())


async def _dispatch_timer(timer):
    from app.routes.push_tokens import send_push_to_user
    await send_push_to_user(
        user_id=timer.user_id,
        title=f"Timer: {timer.title or 'Timer'}",
        body=f"Your {timer.duration_minutes}min timer is done!",
        notification_data={
            "type": "timer_complete",
            "timer_id": timer.id,
            "timer_name": timer.title or "Timer",
        },
    )


async def _dispatch_reminder(reminder):
    from app.routes.push_tokens import send_push_to_user
    await send_push_to_user(
        user_id=reminder.user_id,
        title=f"Reminder: {reminder.title or 'Reminder'}",
        body=reminder.description or reminder.content or "Time for your reminder",
        notification_data={
            "type": "reminder",
            "reminder_id": reminder.id,
            "event_id": getattr(reminder, "event_id", None),
        },
    )


# ── Calendar reminder top-up ───────────────────────────────────────
@celery_app.task(name="app.tasks.inproc_schedulers.calendar_reminder_topup", queue="cognitive")
def calendar_reminder_topup():
    """Daily top-up of reminders for recurring calendar events.

    Extends the rolling 30-day window so recurring events past the initial
    expansion keep getting push notifications.
    """
    from app.db.base import SessionLocal
    from app.services.calendar_reminders import topup_all_recurring

    with SessionLocal() as db:
        try:
            created = topup_all_recurring(db)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("calendar_reminder_topup failed: %s", e)
            return {"created": 0, "error": str(e)}
    return {"created": created}
