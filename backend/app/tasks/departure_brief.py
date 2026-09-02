"""Departure brief — the second (and last) morning push, timed ~25 min before
David leaves for the day (MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 4).

Runs every 5 min, 6-10 AM ET weekdays (scheduled_job 'departure-brief').
Fires once per ET weekday once `now >= departure_time - 25min`, carrying the
actionable stuff the wake anchor (morning brief) deliberately left out: the
next calendar event, commute weather, and any
forward-looking content the deliberation gate queued instead of suppressing
(held_notification rows with held_reason='await_departure'). Anything still
queued and un-drained (weekend, no departure sensed) force-flushes at 10 AM
so nothing sits in the queue forever.
"""
import asyncio
import logging
from datetime import timedelta

from app.celery_app import celery_app
from app.core.timezone import now as local_now, today as local_today
from app.core.config import get_owner_id

logger = logging.getLogger(__name__)

_DAVID = get_owner_id()

_DEFAULT_DEPARTURE_TIME = "07:40"
_LEAD_MINUTES = 25
_FORCE_FLUSH_HOUR = 10


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _get_departure_time(db) -> tuple[int, int]:
    from sqlalchemy import text
    raw = _DEFAULT_DEPARTURE_TIME
    try:
        row = (await db.execute(text(
            "SELECT value FROM app_settings WHERE key = 'weekday_departure_time'"
        ))).fetchone()
        if row and row[0]:
            raw = str(row[0]).strip().strip('"')
    except Exception as e:
        logger.debug(f"departure time lookup failed, using default: {e}")
    try:
        hh, mm = raw.split(":")
        return int(hh), int(mm)
    except Exception:
        hh, mm = _DEFAULT_DEPARTURE_TIME.split(":")
        return int(hh), int(mm)


def _already_away() -> bool:
    try:
        from app.services.activity_state_machine import activity_state_machine, ActivityState
        return activity_state_machine.current.state == ActivityState.AWAY
    except Exception as e:
        logger.debug(f"activity state check skipped: {e}")
        return False


async def _already_handled_today(db, user_id: str, topic: str) -> bool:
    from sqlalchemy import text
    row = (await db.execute(text("""
        SELECT EXISTS(SELECT 1 FROM notification_log WHERE user_id = :uid AND topic = :topic)
    """), {"uid": user_id, "topic": topic})).fetchone()
    return bool(row[0]) if row else False


async def _gather_next_event(db, user_id: str):
    from sqlalchemy import text
    from datetime import datetime
    now = local_now().replace(tzinfo=None)
    today_end = datetime.combine(local_today(), datetime.max.time())
    return (await db.execute(text("""
        SELECT title, start_time, location FROM calendar_event
        WHERE user_id = :uid AND start_time >= :now AND start_time <= :end
          AND title NOT LIKE '%🏋️%'
        ORDER BY start_time LIMIT 1
    """), {"uid": user_id, "now": now, "end": today_end})).fetchone()


async def _gather_weather_line() -> str:
    try:
        from app.services.weather_service import weather_service
        weather = await weather_service.get_weather()
        if weather and weather.current:
            return f"{round(weather.current.temperature)}°F, {weather.current.description}"
    except Exception as e:
        logger.debug(f"departure brief weather skipped: {e}")
    return ""


async def _drain_await_departure(db, user_id: str) -> list:
    from sqlalchemy import text
    return (await db.execute(text("""
        SELECT id, title, message, category FROM held_notification
        WHERE user_id = :uid AND status = 'held' AND held_reason = 'await_departure'
        ORDER BY held_at ASC
    """), {"uid": user_id})).fetchall()


async def _mark_drained(db, ids: list, delivered: bool) -> None:
    from sqlalchemy import text
    if not ids:
        return
    await db.execute(text("""
        UPDATE held_notification SET status = :st, resolved_at = NOW() WHERE id = ANY(:ids)
    """), {"st": "delivered" if delivered else "dropped", "ids": ids})
    await db.commit()


async def _run(user_id: str) -> dict:
    from app.db.session import get_async_session_factory
    from app.services.unified_notification import send_notification, _log_notification

    now = local_now()
    if now.weekday() >= 5:
        return {"effect": "weekend_skip"}

    topic = f"departure_brief:{local_today().isoformat()}"

    sf = get_async_session_factory()
    async with sf() as db:
        if await _already_handled_today(db, user_id, topic):
            return {"effect": "already_handled"}

        if _already_away():
            return {"effect": "already_away_skip"}

        hh, mm = await _get_departure_time(db)
        departure_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        fire_at = departure_dt - timedelta(minutes=_LEAD_MINUTES)
        force_flush = now.hour >= _FORCE_FLUSH_HOUR

        if now < fire_at and not force_flush:
            return {"effect": "not_yet", "fire_at": fire_at.isoformat()}

        lines = []
        event_row = await _gather_next_event(db, user_id)
        if event_row:
            when = event_row.start_time.strftime("%-I:%M %p")
            where = f" ({event_row.location})" if event_row.location else ""
            lines.append(f"{event_row.title} at {when}{where}")

        weather_line = await _gather_weather_line()
        if weather_line:
            lines.append(weather_line)

        queued = await _drain_await_departure(db, user_id)
        for row in queued:
            lines.append(row.title)

        if not lines:
            # Nothing to say — still log the topic so this stops re-checking
            # every 5 min for the rest of the window.
            await _log_notification(
                db, user_id, topic, "schedule", "Departure brief", "nothing to report",
                "normal", "departure_brief", None, 0, sent=False, dedup_blocked=False,
                suppress_reason="nothing_to_report",
            )
            await db.commit()
            return {"effect": "nothing_to_report"}

        message = " · ".join(lines)
        result = await send_notification(
            user_id=user_id, title="Before you go", message=message,
            priority="high", category="schedule", source="departure_brief",
            topic=topic, db=db, _bypass_attention=True,
        )
        await db.commit()
        delivered = bool(result.get("sent"))
        await _mark_drained(db, [r.id for r in queued], delivered)

        logger.info(f"🚗 Departure brief {'sent' if delivered else 'attempted'} for {user_id}: {message[:80]}")
        return {"effect": "sent" if delivered else "attempted", "queued_drained": len(queued)}


@celery_app.task(name="app.tasks.departure_brief.send_departure_brief")
def send_departure_brief():
    """MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 4: the second morning push."""
    return _run_async(_run(_DAVID))
