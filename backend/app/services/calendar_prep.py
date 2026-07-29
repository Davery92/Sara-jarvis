"""
Calendar Prep Service — pre-meeting context notifications.

Checks upcoming calendar events and sends a brief prep notification
with relevant context from memory, notes, and PKG.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


# Same keyword set activity_state_machine.py already uses to recognize a
# workout calendar event, kept in sync so "is this a routine personal event"
# means the same thing everywhere in the codebase rather than drifting.
_ROUTINE_PERSONAL_KEYWORDS = ("gym", "workout", "exercise", "gymnastics", "training", "crossfit")


def _is_routine_personal_event(title: Optional[str]) -> bool:
    t = (title or "").lower()
    return any(kw in t for kw in _ROUTINE_PERSONAL_KEYWORDS)


async def _attendee_history_lines(user_id: str, attendees: list) -> list:
    """One line per named attendee with a real person row: last interaction +
    the nearest open follow-up thread mentioning them (best-effort text match —
    followup_thread has no person_id FK, so this is a name-in-topic match, not
    a hard link)."""
    from app.db.session import get_async_session_factory

    lines = []
    if not attendees:
        return lines
    session_factory = get_async_session_factory()
    async with session_factory() as db:
        for attendee in attendees[:5]:
            name = attendee.get("name") or attendee.get("email")
            email = attendee.get("email")
            if not name:
                continue
            row = None
            if email:
                row = (await db.execute(text("""
                    SELECT canonical_name, last_interaction_at, last_interaction_kind FROM person
                    WHERE user_id=:u AND emails @> CAST(:email_json AS jsonb) LIMIT 1
                """), {"u": user_id, "email_json": f'["{email}"]'})).fetchone()
            if not row:
                row = (await db.execute(text("""
                    SELECT canonical_name, last_interaction_at, last_interaction_kind FROM person
                    WHERE user_id=:u AND canonical_name=:name LIMIT 1
                """), {"u": user_id, "name": name})).fetchone()
            if not row or not row[1]:
                continue

            days_ago = (datetime.now(timezone.utc) - row[1]).days
            line = f"{row[0]} — last {row[2] or 'contact'} {days_ago}d ago"

            thread = (await db.execute(text("""
                SELECT topic FROM followup_thread
                WHERE user_id=:u AND status='open' AND topic ILIKE :pat
                ORDER BY priority DESC LIMIT 1
            """), {"u": user_id, "pat": f"%{name}%"})).fetchone()
            if thread:
                line += f"; open thread: {thread[0]}"
            lines.append(line)
    return lines


async def check_and_send_preps(user_id: str):
    """Send prep notifications ~45 min before an event (with research, if any)."""
    from app.db.session import get_async_session_factory
    from app.core.timezone import now as local_now

    async_session = get_async_session_factory()
    # calendar_event.start_time is naive local (ET) — the window must be too,
    # or every prep fires hours off.
    #
    # Target ~45 min of lead. The scan runs every 15 min, so a 20-min-wide
    # window (35–55) guarantees exactly one tick lands inside it (dedup on
    # topic cal_prep:{event_id} covers the rare double-hit). The old 15–60
    # window could fire a full hour early.
    now = local_now().replace(tzinfo=None)
    window_start = now + timedelta(minutes=35)
    window_end = now + timedelta(minutes=55)

    async with async_session() as db:
        # Find upcoming events
        result = await db.execute(text("""
            SELECT id, title, start_time, location, description, ios_calendar_name, attendees, organizer
            FROM calendar_event
            WHERE user_id = :uid
              AND start_time BETWEEN :start AND :end
              -- All-day events (Pay Day, birthdays) have start_time at midnight;
              -- a "starts in ~45 min" push ~40 min before midnight is just noise.
              -- They belong in the morning brief, not a pre-event buzz.
              AND COALESCE(all_day, FALSE) = FALSE
            ORDER BY start_time ASC
            LIMIT 3
        """), {"uid": user_id, "start": window_start, "end": window_end})
        events = result.fetchall()

    if not events:
        return

    from app.services.calendar_ownership import attendance_role

    for event in events:
        event_id, title, start_time, location, description, calendar_name, attendees, organizer = event

        # Skip prep entirely for events David declined, or broadcast invites
        # he's not organizing — "is this David's meeting" reasoning so a
        # 40-person all-hands doesn't get the same prep as a 1:1 he's running.
        role = attendance_role(organizer, attendees)
        if role.declined:
            logger.info(f"Calendar prep skipped for '{title}': David declined")
            continue
        if role.is_broadcast:
            logger.info(f"Calendar prep skipped for '{title}': broadcast invite ({role.attendee_count} attendees, not organizer)")
            continue
        if _is_routine_personal_event(title):
            # SARA_PROACTIVENESS_AUDIT_AND_PLAN_2026_07_25 §7.2: "a routine
            # workout ... reminder without a conflict" is explicitly listed
            # as usually not worth a push — it's already on the calendar he
            # put it on, and a "starts in 45 min" buzz for the gym adds
            # nothing a routine event doesn't already tell him. Real meeting
            # prep (context, attendee history, research) stays; a bare
            # routine-personal-event ping does not.
            logger.info(f"Calendar prep skipped for '{title}': routine personal event, no prep value")
            continue

        await _prep_for_event(
            user_id, str(event_id), title, start_time, location, description, attendees,
            calendar_name=calendar_name,
        )


async def _prep_for_event(
    user_id: str, event_id: str, title: str, start_time,
    location: Optional[str], description: Optional[str], attendees: Optional[list],
    calendar_name: Optional[str] = None,
):
    """Build and send prep context for a single event."""
    from app.services.unified_notification import send_notification
    from app.services.calendar_ownership import classify_event
    from app.core.timezone import now as local_now
    from app.db.session import get_async_session_factory

    # Check if we already sent prep for this event
    topic = f"cal_prep:{event_id}"

    # N3: generation-side idempotence. The 15-min scan can mint a second prep
    # for the same event (with re-frozen "starts in 36 min" text); the delivery
    # layer dedups it, but only AFTER we've re-run all the memory/PKG/research
    # searches. Skip the whole build if this event was already prepped recently.
    # (An event only needs prepping once; 6h covers the whole pre-event window.)
    try:
        _sf = get_async_session_factory()
        async with _sf() as _idem_db:
            already = (await _idem_db.execute(text("""
                SELECT 1 FROM notification_log
                WHERE user_id = :uid AND topic = :topic
                  AND sent_at >= NOW() - INTERVAL '6 hours'
                LIMIT 1
            """), {"uid": user_id, "topic": topic})).first()
        if already:
            logger.info(f"Calendar prep skipped for event {event_id}: already prepped within 6h")
            return
    except Exception as e:
        logger.debug(f"Calendar prep idempotence check skipped: {e}")

    ownership = classify_event(title, calendar_name)
    attendee_names = [a.get("name") or a.get("email") for a in (attendees or []) if a.get("name") or a.get("email")]
    attendees_str = ", ".join(n for n in attendee_names if n) or None

    # Build context from memory and notes — only for David's own events;
    # pulling his memories for someone else's appointment produces nonsense.
    context_parts = []
    if ownership.is_self:
        # Person history for named attendees (Phase 5.4) — real relationship
        # context beats a generic PKG search: "Mike — last emailed 6/24;
        # open thread: waiting on his pricing sheet."
        try:
            person_lines = await _attendee_history_lines(user_id, attendees or [])
            context_parts.extend(person_lines)
        except Exception as e:
            logger.debug(f"Calendar prep attendee history failed: {e}")

        # Search episodic memory for related context
        try:
            from app.services.memory_service import search_episodes
            search_query = title
            if attendees_str:
                search_query += f" {attendees_str}"
            episodes = await search_episodes(user_id, search_query, limit=3)
            if episodes:
                memories = [f"- {ep.get('content', '')[:150]}" for ep in episodes[:2]]
                if memories:
                    context_parts.append("Previous context:\n" + "\n".join(memories))
        except Exception as e:
            logger.debug(f"Calendar prep memory search failed: {e}")

        # Search PKG for relevant facts
        try:
            from app.services.pkg_context_provider import get_pkg_context
            pkg_ctx = await get_pkg_context(user_id, title)
            if pkg_ctx and len(pkg_ctx) > 20:
                context_parts.append(f"Related: {pkg_ctx[:200]}")
        except Exception as e:
            logger.debug(f"Calendar prep PKG search failed: {e}")

        # Business-meeting enrichment: counterparty company + any ready research.
        # meeting_research is synchronous, so use a short-lived sync session.
        try:
            from app.services.meeting_research import build_prep
            from app.db.session import SessionLocal
            with SessionLocal() as sdb:
                mprep = build_prep(sdb, user_id, {
                    "title": title,
                    "description": description or "",
                    "location": location or "",
                    "start_time": start_time,
                    "ios_calendar_name": calendar_name,
                })
            if mprep["is_business_meeting"]:
                if mprep["companies"]:
                    context_parts.append("With: " + ", ".join(mprep["companies"][:3]))
                for r in mprep["research"]:
                    if r.get("summary"):
                        context_parts.append(f"Research ({r['company']}): {r['summary'][:200]}")
        except Exception as e:
            logger.debug(f"Calendar prep meeting research failed: {e}")

    # Build notification. start_time is naive local (ET); compare in ET.
    now_local = local_now().replace(tzinfo=None)
    minutes_until = max(0, int((start_time - now_local).total_seconds() / 60))
    time_str = f"in {minutes_until} min" if minutes_until > 0 else "now"

    # Attribute someone else's event to them, never to David
    display_title = title if ownership.is_self else f"{ownership.label}: {title}"

    message_parts = [f"{display_title} starts {time_str}"]
    if location:
        message_parts.append(f"at {location}")

    message = ". ".join(message_parts[:2])
    if context_parts:
        message += "\n" + "\n".join(context_parts)

    stimulus_key = f"calendar_prep:{event_id}"
    try:
        from app.services.habituation import should_generate
        if not await should_generate(db, "calendar_prep", stimulus_key):
            logger.info(f"Calendar prep habituated for '{display_title}'")
            return
    except Exception as e:
        logger.debug(f"Calendar prep habituation check skipped: {e}")

    await send_notification(
        user_id=user_id,
        title=f"Upcoming: {display_title}",
        message=message[:500],
        # Push at creation — we're already 35-55 min out, which is exactly when
        # the reminder is useful. "high" is what actually leaves as a push
        # (normal/important stay inbox-only and would only ever reach the phone
        # via the 2h escalation, which is always too late for a timed event).
        priority="high",
        category="calendar_prep",
        topic=topic,
        source="calendar_prep",
        payload={
            "prediction_grade": "novel",
            "stimulus_key": stimulus_key,
            "generator": "calendar_prep",
        },
    )
    logger.info(f"Calendar prep sent for '{display_title}' ({time_str})")

    # Mind V2 rewire plan Workstream B.3 — dual-write the same real content
    # into the say_candidate queue. Legacy send above is untouched; this is
    # additive only, wrapped so a candidate-queue failure never breaks the
    # legacy send while it's still the delivery path.
    try:
        from app.core.timezone import to_utc
        from app.services.say_candidate import create_candidate

        valid_until = to_utc(start_time)  # naive ET wall-clock -> aware UTC
        cand_factory = get_async_session_factory()
        async with cand_factory() as cand_db:
            await create_candidate(
                cand_db, user_id=user_id, source="calendar_prep", kind="prep",
                summary=message[:2000],
                evidence=[{"event_id": event_id, "topic": topic}],
                topic_entities=[topic],
                valid_until=valid_until,
                dedupe_key=topic,
            )
    except Exception as e:
        logger.warning(f"[say_candidate] calendar_prep dual-write failed: {e}")

    # SARA_UNLEASHED Phase C.1: meeting preps are an autonomous action like any
    # other and belong in the same auditable ledger (Z-4 invariant).
    try:
        from app.services.deliberation_gate import _write_action_ledger
        await _write_action_ledger(
            user_id, "meeting_prep", f"Prepped for '{display_title}' ({time_str})",
            source_ref=event_id,
        )
    except Exception as e:
        logger.debug(f"Calendar prep action_ledger write skipped: {e}")
