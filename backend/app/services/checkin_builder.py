"""
Check-in Builder — deterministic, template-driven check-in generation.

Builds personalized check-in messages based on actual context:
- What happened while David was away
- Upcoming events
- Current activity state
- Active projects/learning

No LLM calls — pure template logic. Returns None if nothing warrants a check-in.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.services.unified_context import UnifiedContextSnapshot

logger = logging.getLogger(__name__)


def _silence_hours(snapshot: UnifiedContextSnapshot) -> float:
    """Hours of true silence — the smaller of 'since last chat' and 'since last
    app activity'. Being in the app (logging food, workouts) is contact, so an
    ambient 'you've been quiet' check-in shouldn't fire just because he hasn't
    *talked*. Conversation-recency (hours_since_last_chat) stays separate."""
    chat = snapshot.hours_since_last_chat or 0.0
    app = snapshot.hours_since_app_activity if snapshot.hours_since_app_activity is not None else 999.0
    return min(chat, app)


def build_checkin(
    snapshot: UnifiedContextSnapshot,
    changes: List[str],
    recent_actions: Optional[List[Dict]] = None,
    open_threads: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """
    Build a check-in notification if conditions warrant one.

    Returns:
        Dict with {title, message, priority, topic} or None if no check-in needed.
    """
    # ── Gate checks ──
    # Silence, not conversation-recency: if he's been active in the app in the
    # last 2h he isn't "quiet" — don't fire an ambient check-in at him.
    if _silence_hours(snapshot) < 2.0:
        return None  # Too recent (talked or in-app)

    if snapshot.activity_state == "SLEEPING":
        return None

    if snapshot.is_past_bedtime and snapshot.activity_state == "WINDING_DOWN":
        return None  # Don't interrupt wind-down

    # ── Thread-based check-in (most personal, highest priority) ──
    if open_threads:
        thread = open_threads[0]  # already sorted by priority
        followup = thread.get("suggested_followup", "")
        if followup:
            return {
                "title": "Hey David",
                "message": followup,
                "priority": "normal",
                "topic": f"thread:{thread['id'][:8]}",
                "thread_id": thread.get("id"),
            }

    has_changes = bool(changes)
    has_upcoming = bool(snapshot.next_event_title and snapshot.next_event_minutes_away is not None
                        and snapshot.next_event_minutes_away <= 60)
    has_reviews = False  # learning reviews disabled

    # Nothing to say — skip
    if not has_changes and not has_upcoming and not has_reviews:
        return None

    # ── Build message ──
    parts = []
    priority = "normal"
    topic = "checkin"

    # Upcoming event (highest priority)
    if has_upcoming and snapshot.next_event_minutes_away is not None:
        mins = snapshot.next_event_minutes_away
        if mins <= 15:
            parts.append(f"Your {snapshot.next_event_title} starts in {mins} minutes.")
            priority = "important"
            topic = "calendar_reminder"
        elif mins <= 30:
            parts.append(f"{snapshot.next_event_title} is in {mins} minutes.")
            priority = "important"
            topic = "calendar_reminder"
        else:
            parts.append(f"Heads up: {snapshot.next_event_title} in about {mins} minutes.")

    # Changes while away
    if has_changes:
        n = len(changes)
        if n <= 3:
            change_summaries = [c.split("] ", 1)[-1] if "] " in c else c for c in changes[-3:]]
            parts.append("While you were away: " + ". ".join(change_summaries) + ".")
        else:
            parts.append(f"I have {n} updates from while you were away.")

    # Learning reviews
    if has_reviews and not has_upcoming:
        if snapshot.learning_reviews_due <= 3:
            parts.append(f"You have {snapshot.learning_reviews_due} learning review(s) due when you have a moment.")
        else:
            parts.append(f"{snapshot.learning_reviews_due} learning reviews are piling up.")

    # Active project reference (makes it personal)
    if snapshot.active_projects and not has_upcoming:
        project = snapshot.active_projects[0]
        hours = _silence_hours(snapshot)
        if hours > 4:
            parts.append(f"You've been heads-down for {hours:.0f} hours. How's {project} going?")

    if not parts:
        return None

    # ── Tone adaptation ──
    message = " ".join(parts)
    title = _build_title(snapshot, has_upcoming, priority)

    return {
        "title": title,
        "message": message,
        "priority": priority,
        "topic": topic,
    }


def _build_title(
    snapshot: UnifiedContextSnapshot,
    has_upcoming: bool,
    priority: str,
) -> str:
    """Build a short notification title based on context."""
    if has_upcoming:
        return "Upcoming event"

    if snapshot.activity_state == "FOCUSED_WORK":
        return "Quick update"

    hours = _silence_hours(snapshot)
    if hours > 6:
        return "Checking in"

    return "Hey David"
