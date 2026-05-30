"""Bridge calendar events to the reminder/notification system.

When a calendar event has ``reminder_minutes`` set, we materialize matching
``Reminder`` rows so the existing notification predispatch loop fires a push
at the right time. Recurring events expand into one reminder per occurrence
within a rolling window; a daily Celery task tops the window up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dateutil import rrule as _rrule
from sqlalchemy.orm import Session

from app.core.timezone import USER_TIMEZONE, to_utc
from app.models.reminder import Reminder
from app.tools.calendar import CalendarEvent

# How far ahead to materialize occurrences for recurring events
RECURRING_HORIZON_DAYS = 30


def _event_local_start(event: CalendarEvent) -> datetime:
    """Return event.start_time as a TZ-aware ET datetime."""
    start = event.start_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=USER_TIMEZONE)
    else:
        start = start.astimezone(USER_TIMEZONE)
    return start


def _expand_occurrences(event: CalendarEvent, horizon_days: int = RECURRING_HORIZON_DAYS) -> List[datetime]:
    """Return future occurrence start times (TZ-aware ET) within the horizon."""
    base = _event_local_start(event)
    now_local = datetime.now(USER_TIMEZONE)
    horizon = now_local + timedelta(days=horizon_days)

    if not getattr(event, "rrule", None):
        if base >= now_local:
            return [base]
        return []

    try:
        rule = _rrule.rrulestr(event.rrule, dtstart=base)
    except Exception:
        # Malformed RRULE — fall back to the base occurrence only
        if base >= now_local:
            return [base]
        return []

    occurrences: List[datetime] = []
    for dt in rule:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=USER_TIMEZONE)
        if dt < now_local:
            continue
        if dt > horizon:
            break
        occurrences.append(dt)
    return occurrences


def _build_reminder(event: CalendarEvent, occurrence_local: datetime) -> Optional[Reminder]:
    if event.reminder_minutes is None:
        return None
    fire_local = occurrence_local - timedelta(minutes=int(event.reminder_minutes))
    if fire_local <= datetime.now(USER_TIMEZONE):
        # Already past — skip rather than spam an immediate push
        return None
    fire_utc = to_utc(fire_local)

    body = f"Starts at {occurrence_local.strftime('%-I:%M %p')}"
    if event.location:
        body += f" — {event.location}"

    return Reminder(
        user_id=event.user_id,
        title=event.title,
        description=body,
        reminder_time=fire_utc,
        is_completed=False,
        event_id=event.id,
    )


def clear_event_reminders(db: Session, event_id: str) -> int:
    """Delete pending reminders for an event. Returns count removed."""
    deleted = (
        db.query(Reminder)
        .filter(Reminder.event_id == event_id, Reminder.is_completed.is_(False))
        .delete(synchronize_session=False)
    )
    return deleted


def sync_event_reminders(db: Session, event: CalendarEvent) -> int:
    """Reconcile reminders for a single event.

    Removes any pending reminders that no longer match the event's schedule and
    inserts reminders for occurrences within the horizon that don't have one.
    Returns the number of reminders created (net new).

    Skips events with read_only=True (iOS handles those natively).
    Skips events without reminder_minutes set (caller intent is "no push").
    """
    if getattr(event, "read_only", False):
        clear_event_reminders(db, event.id)
        return 0

    if event.reminder_minutes is None or event.is_completed:
        clear_event_reminders(db, event.id)
        return 0

    target_occurrences = _expand_occurrences(event)
    if not target_occurrences:
        clear_event_reminders(db, event.id)
        return 0

    # Compute desired fire times (UTC) for fast diffing
    desired_fire_utc = set()
    for occ in target_occurrences:
        fire_local = occ - timedelta(minutes=int(event.reminder_minutes))
        if fire_local <= datetime.now(USER_TIMEZONE):
            continue
        desired_fire_utc.add(to_utc(fire_local).replace(microsecond=0))

    existing = (
        db.query(Reminder)
        .filter(Reminder.event_id == event.id, Reminder.is_completed.is_(False))
        .all()
    )
    existing_fire_utc = set()
    for r in existing:
        rt = r.reminder_time
        if rt.tzinfo is None:
            rt = rt.replace(tzinfo=timezone.utc)
        else:
            rt = rt.astimezone(timezone.utc)
        existing_fire_utc.add(rt.replace(microsecond=0))

    # Drop reminders that no longer match (time changed, rrule narrowed, etc.)
    for r in existing:
        rt = r.reminder_time
        if rt.tzinfo is None:
            rt = rt.replace(tzinfo=timezone.utc)
        else:
            rt = rt.astimezone(timezone.utc)
        if rt.replace(microsecond=0) not in desired_fire_utc:
            db.delete(r)

    # Insert missing
    created = 0
    for occ in target_occurrences:
        fire_local = occ - timedelta(minutes=int(event.reminder_minutes))
        if fire_local <= datetime.now(USER_TIMEZONE):
            continue
        fire_utc = to_utc(fire_local).replace(microsecond=0)
        if fire_utc in existing_fire_utc:
            continue
        reminder = _build_reminder(event, occ)
        if reminder is not None:
            db.add(reminder)
            created += 1

    return created


def topup_all_recurring(db: Session) -> int:
    """Top up reminders for all recurring events with a reminder_minutes set.

    Idempotent — only inserts missing reminders within the horizon.
    """
    events = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.rrule.isnot(None),
            CalendarEvent.reminder_minutes.isnot(None),
        )
        .all()
    )
    total = 0
    for event in events:
        if getattr(event, "read_only", False):
            continue
        total += sync_event_reminders(db, event)
    return total
