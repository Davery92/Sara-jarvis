"""Clock-driven facts happen without an app launch.

This module is also where invariant 3 — *everything open has a closer and an
expiry* — is enforced between nightly runs: a meeting that ended closes the
threads that referenced it, an overdue thread says so exactly once, and anything
past its window expires on its own rather than nagging forever.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.timezone import naive_local_now, render_when
from app.models.calendar_event import CalendarEvent
from app.models.world_model import SaraPresenceSnapshot, WorldThread
from app.services.world_state.writer import append_world_event

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("proposed", "open", "waiting", "blocked")

# How long past its moment an open thing stays open. A thread with a real
# deadline gets a grace period; one with no deadline gets a fortnight of silence
# before it is assumed dead. Reminders that never fired are dead after a week.
DUE_THREAD_GRACE = timedelta(hours=48)
UNDATED_THREAD_LIFETIME = timedelta(days=14)


def _title_tokens(title: str) -> List[str]:
    """Distinctive words from an event title, for matching a thread against it."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", title or "")
    return [w.lower() for w in words][:6]


def _resolve_threads_for_calendar_event(db: Session, event_row) -> int:
    """A meeting that ended closes the threads that were about it.

    Matched by explicit reference (`source_ref` naming the calendar event) or by
    the event's own distinctive title words appearing in the thread title. The
    title match is deliberately conservative — it needs a word of four letters or
    more from the meeting name — because closing too eagerly loses real work,
    while closing too rarely is the failure this whole plan exists to fix.
    """
    tokens = _title_tokens(event_row.title)
    conditions = [WorldThread.thread_key.contains(f"calendar:{event_row.id}")]
    conditions.append(WorldThread.thread_key.contains(str(event_row.id)))
    for token in tokens:
        conditions.append(WorldThread.title.ilike(f"%{token}%"))

    rows = db.execute(select(WorldThread).where(
        WorldThread.user_id == event_row.user_id,
        WorldThread.status.in_(ACTIVE_STATUSES),
        WorldThread.kind.in_(("follow_up", "commitment", "prep", "meeting")),
        or_(*conditions),
    ).limit(20)).scalars().all()
    if not rows:
        return 0

    append_world_event(
        db, user_id=event_row.user_id, kind="thread.resolved",
        source="calendar_ended", source_ref=f"calendar_event:{event_row.id}",
        aggregate_type="world_thread", aggregate_id=rows[0].id,
        dedupe_key=f"thread-resolved:calendar:{event_row.id}:{event_row.end_time.isoformat()}",  # time-ok: dedupe key
        payload={
            "thread_ids": [r.id for r in rows],
            "reason": f"'{event_row.title}' has ended",
        },
    )
    return len(rows)


def _expire_stale_threads(db: Session, now: datetime) -> int:
    """Hard expiry. Nothing stays open because nobody looked at it."""
    overdue = db.execute(select(WorldThread).where(
        WorldThread.status.in_(ACTIVE_STATUSES),
        WorldThread.due_at.is_not(None),
        WorldThread.due_at < now - DUE_THREAD_GRACE,
    ).limit(250)).scalars().all()

    undated = db.execute(select(WorldThread).where(
        WorldThread.status.in_(ACTIVE_STATUSES),
        WorldThread.due_at.is_(None),
        WorldThread.updated_at < now - UNDATED_THREAD_LIFETIME,
    ).limit(250)).scalars().all()

    expired = 0
    for thread in list(overdue) + list(undated):
        thread.status = "expired"
        thread.resolved_at = now
        expired += 1
    if expired:
        logger.info("[temporal] expired %d stale thread(s)", expired)
    return expired


def _complete_dead_reminders(db: Session, now: datetime) -> int:
    """A reminder that never fired is not a reminder, it is a grudge."""
    from sqlalchemy import text as sa_text

    # reminder_time is a naive ET wall-clock column; binding an aware UTC
    # cutoff against it compares the wrong two things.
    result = db.execute(sa_text("""
        UPDATE reminder SET is_completed = true
         WHERE is_completed = false
           AND reminder_time IS NOT NULL
           AND reminder_time < :cutoff
        RETURNING id
    """), {"cutoff": naive_local_now() - timedelta(days=7)})
    return len(result.fetchall())


def synthesize(db: Session) -> Dict[str, int]:
    now = datetime.now(timezone.utc)
    emitted = 0
    presence_reset = 0
    threads_closed = 0

    for row in db.execute(
        select(SaraPresenceSnapshot).where(
            SaraPresenceSnapshot.valid_until <= now,
            SaraPresenceSnapshot.state != "resting",
        ).with_for_update(skip_locked=True)
    ).scalars().all():
        row.state = "resting"
        row.headline = "Available"
        row.detail = None
        row.task_id = None
        row.revision = (row.revision or 0) + 1
        row.updated_at = now
        row.valid_until = now + timedelta(minutes=5)
        presence_reset += 1

    # Overdue fires once. The old query re-selected every open past-due thread on
    # every sweep; the dedupe_key stopped duplicate *events*, but the thread kept
    # coming back into the deliberation whiteboard as fresh news. Moving it to
    # status='overdue' takes it out of the active set permanently — it is still
    # visible, still closeable, but it has already said its piece.
    for thread in db.execute(
        select(WorldThread).where(
            WorldThread.status.in_(ACTIVE_STATUSES),
            WorldThread.due_at.is_not(None), WorldThread.due_at <= now,
        ).limit(250)
    ).scalars().all():
        event = append_world_event(
            db, user_id=thread.user_id, kind="thread.overdue", source="temporal_synthesizer",
            source_ref=f"world_thread:{thread.id}", aggregate_type="world_thread",
            aggregate_id=thread.id, occurred_at=thread.due_at,
            dedupe_key=f"thread-overdue:{thread.id}:{thread.due_at.isoformat()}",  # time-ok: dedupe key
            payload={
                "thread_id": thread.id, "title": thread.title,
                "due_at": thread.due_at.isoformat(),  # time-ok: stored value; due_text is what prompts read
                # Invariant 4: one clock. Everything downstream — observation
                # text, attention description, the deliberation prompt — reads
                # due_text and never the raw stamp. A thread due 17:00Z was being
                # announced as "your 5:00 AM EDT call".
                "due_text": render_when(thread.due_at, now=now),
                "due_provenance": thread.due_provenance,
                "urgency": 0.8,
            },
        )
        emitted += int(event is not None)
        thread.status = "overdue"

    # calendar_event stores local wall time without a timezone. Compare against
    # local wall time, but publish a UTC observation and retain the raw boundary.
    local_now = naive_local_now()
    window_start = local_now - timedelta(minutes=2)
    rows = db.execute(select(CalendarEvent).where(
        CalendarEvent.start_time <= local_now,
        CalendarEvent.end_time >= window_start,
    ).limit(500)).scalars().all()
    for event_row in rows:
        if window_start <= event_row.start_time <= local_now:
            event = append_world_event(
                db, user_id=event_row.user_id, kind="calendar.started", source="temporal_synthesizer",
                source_ref=f"calendar_event:{event_row.id}", aggregate_type="calendar_event", aggregate_id=event_row.id,
                dedupe_key=f"calendar-started:{event_row.id}:{event_row.start_time.isoformat()}",  # time-ok: dedupe key
                payload={"title": event_row.title, "start_time": event_row.start_time.isoformat(), "end_time": event_row.end_time.isoformat(), "location": event_row.location},  # time-ok: stored values
            )
            emitted += int(event is not None)
        if window_start <= event_row.end_time <= local_now:
            event = append_world_event(
                db, user_id=event_row.user_id, kind="calendar.ended", source="temporal_synthesizer",
                source_ref=f"calendar_event:{event_row.id}", aggregate_type="calendar_event", aggregate_id=event_row.id,
                dedupe_key=f"calendar-ended:{event_row.id}:{event_row.end_time.isoformat()}",  # time-ok: dedupe key
                payload={"title": event_row.title, "start_time": event_row.start_time.isoformat(), "end_time": event_row.end_time.isoformat(), "location": event_row.location},  # time-ok: stored values
            )
            emitted += int(event is not None)
            if event is not None:
                threads_closed += _resolve_threads_for_calendar_event(db, event_row)

    expired = _expire_stale_threads(db, now)
    try:
        reminders_closed = _complete_dead_reminders(db, now)
    except Exception as e:
        logger.warning("[temporal] reminder expiry skipped: %s", e)
        reminders_closed = 0

    db.commit()
    return {
        "events_emitted": emitted,
        "presence_reset": presence_reset,
        "threads_closed": threads_closed,
        "threads_expired": expired,
        "reminders_expired": reminders_closed,
    }
