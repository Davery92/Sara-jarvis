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
            SELECT id, title, start_time, location, description, ios_calendar_name
            FROM calendar_event
            WHERE user_id = :uid
              AND start_time BETWEEN :start AND :end
            ORDER BY start_time ASC
            LIMIT 3
        """), {"uid": user_id, "start": window_start, "end": window_end})
        events = result.fetchall()

    if not events:
        return

    for event in events:
        event_id, title, start_time, location, description, calendar_name = event
        await _prep_for_event(
            user_id, str(event_id), title, start_time, location, description, None,
            calendar_name=calendar_name,
        )


async def _prep_for_event(
    user_id: str, event_id: str, title: str, start_time,
    location: Optional[str], description: Optional[str], attendees: Optional[str],
    calendar_name: Optional[str] = None,
):
    """Build and send prep context for a single event."""
    from app.services.unified_notification import send_notification
    from app.services.calendar_ownership import classify_event
    from app.core.timezone import now as local_now

    # Check if we already sent prep for this event
    topic = f"cal_prep:{event_id}"

    ownership = classify_event(title, calendar_name)

    # Build context from memory and notes — only for David's own events;
    # pulling his memories for someone else's appointment produces nonsense.
    context_parts = []
    if ownership.is_self:
        # Search episodic memory for related context
        try:
            from app.services.memory_service import search_episodes
            search_query = title
            if attendees:
                search_query += f" {attendees}"
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

    await send_notification(
        user_id=user_id,
        title=f"Upcoming: {display_title}",
        message=message[:500],
        priority="normal" if minutes_until > 15 else "important",
        category="calendar_prep",
        topic=topic,
        source="calendar_prep",
    )
    logger.info(f"Calendar prep sent for '{display_title}' ({time_str})")
