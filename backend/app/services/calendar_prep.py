"""
Calendar Prep Service — pre-meeting context notifications.

Checks upcoming calendar events and sends a brief prep notification
with relevant context from memory, notes, and PKG.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def check_and_send_preps(user_id: str):
    """Check upcoming events in the next 15-60 min and send prep notifications."""
    from app.db.session import get_async_session_factory

    async_session = get_async_session_factory()
    now = datetime.utcnow()
    window_start = now + timedelta(minutes=15)
    window_end = now + timedelta(minutes=60)

    async with async_session() as db:
        # Find upcoming events
        result = await db.execute(text("""
            SELECT id, title, start_time, location, description
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
        event_id, title, start_time, location, description = event
        await _prep_for_event(user_id, str(event_id), title, start_time, location, description, None)


async def _prep_for_event(
    user_id: str, event_id: str, title: str, start_time,
    location: Optional[str], description: Optional[str], attendees: Optional[str]
):
    """Build and send prep context for a single event."""
    from app.services.unified_notification import send_notification

    # Check if we already sent prep for this event
    topic = f"cal_prep:{event_id}"

    # Build context from memory and notes
    context_parts = []

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

    # Build notification
    minutes_until = max(0, int((start_time.replace(tzinfo=None) - datetime.utcnow()).total_seconds() / 60))
    time_str = f"in {minutes_until} min" if minutes_until > 0 else "now"

    message_parts = [f"{title} starts {time_str}"]
    if location:
        message_parts.append(f"at {location}")
    if context_parts:
        message_parts.append("\n" + "\n".join(context_parts))

    message = ". ".join(message_parts[:2])
    if context_parts:
        message += "\n" + "\n".join(context_parts)

    await send_notification(
        user_id=user_id,
        title=f"Upcoming: {title}",
        message=message[:500],
        priority="normal" if minutes_until > 15 else "important",
        category="calendar_prep",
        topic=topic,
        source="calendar_prep",
    )
    logger.info(f"Calendar prep sent for '{title}' ({time_str})")
