"""
Salience Scorer — determines how interesting each event is to Sara.

Every event gets a salience score (0.0-1.0). Events above 0.3 become
observations. When accumulated observation salience crosses a threshold,
deliberation is triggered.

Scoring dimensions (weighted):
  - Time sensitivity (0.35): calendar approaching, reminder overdue, aging items
  - Novelty (0.25): first occurrence, pattern breaks, new information
  - Emotional relevance (0.20): topics David cares about, mentioned repeatedly
  - Accumulation (0.10): multiple small things in same category
  - Staleness (0.10): unacted observations + hours since last chat

Usage:
    from app.services.salience import salience_scorer
    score = await salience_scorer.score_event(event, memory)
    if await salience_scorer.should_deliberate(user_id):
        trigger_deliberation()
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.event_bus import Event, EventType
from app.services.unified_context import UnifiedContextSnapshot

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")


def _describe_focus_span(payload: dict) -> str:
    """Compact focus-span description. Prefers domain+page over raw app+window
    when the browser extension has enriched the span."""
    dur = _fmt_duration(payload.get("duration_seconds", 0))
    domain = payload.get("domain")
    page = payload.get("page_title")
    if domain:
        if page:
            return f"Desktop: {dur} on {domain} — {page[:60]}"
        return f"Desktop: {dur} on {domain}"
    app = payload.get("app") or "unknown app"
    window = payload.get("window")
    if window:
        return f"Desktop: {dur} in {app} — {window[:60]}"
    return f"Desktop: {dur} in {app}"


def _fmt_duration(seconds: float) -> str:
    """Compact human duration: 45s, 3m, 1h12m."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "?"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, rem = divmod(s, 3600)
    return f"{h}h{rem // 60:02d}m"

# Deliberation thresholds. SALIENCE_THRESHOLD and MAX_DELIBERATION_GAP_HOURS
# are runtime-overridable via tunable_setting (`acs.salience_threshold`,
# `acs.max_deliberation_gap_hours`) — these constants are fallback defaults.
SALIENCE_THRESHOLD = 1.5  # accumulated salience needed to trigger deliberation
MIN_DELIBERATION_GAP_MINUTES = 20  # rate limit between deliberations
MAX_DELIBERATION_GAP_HOURS = 1.5  # force deliberation if idle this long (waking hours)
OBSERVATION_FLOOR = 0.3  # events below this don't become observations
NIGHT_HOURS = (1, 5)  # 1 AM - 5 AM: no deliberation unless critical

# Weights
W_TIME_SENSITIVITY = 0.35
W_NOVELTY = 0.25
W_EMOTIONAL_RELEVANCE = 0.20
W_ACCUMULATION = 0.10
W_STALENESS = 0.10

# Rhythm deviation floor — modest on its own, but stacks with staleness/accumulation
# to tip deliberation. Never a hard trigger by itself (see daily_rhythm.get_off_rhythm_flags).
RHYTHM_DEVIATION_FLOOR = 0.4


def _parse_utc_iso(iso_str: str) -> datetime:
    """Parse an ISO timestamp, ensuring it's tz-aware UTC."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SalienceScorer:
    """Scores events for salience and decides when to trigger deliberation."""

    async def score_event(
        self, event: Event, memory: UnifiedContextSnapshot
    ) -> float:
        """
        Score an event's salience given current working memory context.
        Returns 0.0-1.0.
        """
        scores = {
            "time_sensitivity": self._score_time_sensitivity(event, memory),
            "novelty": self._score_novelty(event, memory),
            "emotional_relevance": self._score_emotional_relevance(event, memory),
            "accumulation": self._score_accumulation(event, memory),
            "staleness": self._score_staleness(event, memory),
        }

        weighted = (
            scores["time_sensitivity"] * W_TIME_SENSITIVITY
            + scores["novelty"] * W_NOVELTY
            + scores["emotional_relevance"] * W_EMOTIONAL_RELEVANCE
            + scores["accumulation"] * W_ACCUMULATION
            + scores["staleness"] * W_STALENESS
        )

        # Category-specific floors
        final = self._apply_category_floors(event, weighted)

        logger.debug(
            f"[Salience] {event.event_type.value}: {final:.2f} "
            f"(time={scores['time_sensitivity']:.2f} novel={scores['novelty']:.2f} "
            f"emot={scores['emotional_relevance']:.2f} accum={scores['accumulation']:.2f} "
            f"stale={scores['staleness']:.2f})"
        )
        return min(max(final, 0.0), 1.0)

    def _score_time_sensitivity(self, event: Event, memory: UnifiedContextSnapshot) -> float:
        """How time-sensitive is this event?"""
        etype = event.event_type

        # Calendar events within 90 minutes
        if etype in (EventType.CALENDAR_EVENT_CREATED, EventType.CALENDAR_EVENT_UPDATED):
            start_str = event.payload.get("start_time")
            if start_str:
                try:
                    start = datetime.fromisoformat(start_str)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=USER_TZ)
                    minutes_away = (start - datetime.now(USER_TZ)).total_seconds() / 60
                    if 0 < minutes_away <= 90:
                        return min(1.0, 1.0 - (minutes_away / 90))
                except (ValueError, TypeError):
                    pass
            return 0.2

        # Next event approaching (from memory)
        if memory.next_event_minutes_away and 0 < memory.next_event_minutes_away <= 30:
            if etype == EventType.CONTEXT_UPDATED:
                return min(1.0, 1.0 - (memory.next_event_minutes_away / 30))

        # Timer completion
        if etype == EventType.TIMER_COMPLETED:
            return 0.7

        # Reminder completion
        if etype in (EventType.REMINDER_CREATED, EventType.REMINDER_COMPLETED):
            return 0.4

        return 0.1

    def _score_novelty(self, event: Event, memory: UnifiedContextSnapshot) -> float:
        """How novel/unexpected is this event?"""
        etype = event.event_type

        # Security events are always novel
        if etype in (EventType.HOME_DOOR_CHANGED, EventType.HOME_ANOMALY_DETECTED):
            return 0.8

        # Chat message after long silence
        if etype == EventType.CHAT_MESSAGE_RECEIVED:
            if memory.hours_since_last_chat > 4:
                return 0.6
            return 0.2

        # Food logged after long gap
        if etype == EventType.FOOD_LOGGED:
            if memory.hours_since_last_meal > 6:
                return 0.5
            return 0.2

        # Activity state change
        if etype == EventType.ACTIVITY_STATE_CHANGED:
            new_state = event.payload.get("state", "")
            old_state = memory.activity_state
            if new_state != old_state:
                return 0.5
            return 0.1

        # Note creation is mildly novel
        if etype in (EventType.NOTE_CREATED, EventType.NOTE_UPDATED):
            return 0.3

        # Workout events
        if etype in (EventType.WORKOUT_LOGGED, EventType.WORKOUT_COMPLETED):
            return 0.4

        # Location transitions — a place change is novel; arriving home after
        # a long absence is the most novel of all.
        if etype in (EventType.LOCATION_PLACE_ENTERED, EventType.LOCATION_PLACE_EXITED):
            place_type = event.payload.get("place_type", "")
            if etype == EventType.LOCATION_PLACE_ENTERED and place_type == "home":
                return 0.7
            return 0.4

        return 0.1

    def _score_emotional_relevance(self, event: Event, memory: UnifiedContextSnapshot) -> float:
        """How emotionally relevant is this to David?"""
        etype = event.event_type

        # Security events — always high emotional relevance
        if etype in (EventType.HOME_DOOR_CHANGED, EventType.HOME_ANOMALY_DETECTED):
            return 0.9

        # Chat topics matching Sara's focus or curiosities
        if etype == EventType.CHAT_MESSAGE_RECEIVED:
            topic = event.payload.get("topic", "")
            if memory.sara_focus and memory.sara_focus.lower() in topic.lower():
                return 0.6
            if memory.sara_curiosities:
                for curiosity in memory.sara_curiosities:
                    if curiosity.lower() in topic.lower():
                        return 0.5
            return 0.3  # all chat is somewhat relevant

        # Goal progress
        if etype in (EventType.GOAL_PROGRESS_LOGGED, EventType.GOAL_MILESTONE_REACHED, EventType.GOAL_COMPLETED):
            return 0.7

        # Health data
        if etype == EventType.HEALTH_DATA_SYNCED:
            return 0.3

        # Location — where David is matters, especially arriving/leaving home
        if etype in (EventType.LOCATION_PLACE_ENTERED, EventType.LOCATION_PLACE_EXITED):
            place_type = event.payload.get("place_type", "")
            if place_type == "home":
                return 0.5
            return 0.3

        return 0.1

    def _score_accumulation(self, event: Event, memory: UnifiedContextSnapshot) -> float:
        """How much is accumulating in this category?"""
        # Use observation count as a proxy — more pending = higher accumulation pressure
        obs_count = memory.observation_count
        if obs_count >= 10:
            return 0.8
        elif obs_count >= 5:
            return 0.5
        elif obs_count >= 2:
            return 0.3
        return 0.1

    def _score_staleness(self, event: Event, memory: UnifiedContextSnapshot) -> float:
        """How stale is Sara's awareness? Long silence = higher salience for everything."""
        hours_since_chat = memory.hours_since_last_chat or 0.0

        # Hours since last deliberation
        hours_since_deliberation = 0.0
        if memory.sara_last_deliberation_at:
            try:
                last_delib = _parse_utc_iso(memory.sara_last_deliberation_at)
                hours_since_deliberation = (datetime.now(timezone.utc) - last_delib).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        # More stale = everything scores higher
        chat_staleness = min(1.0, hours_since_chat / 8.0)  # maxes at 8 hours
        delib_staleness = min(1.0, hours_since_deliberation / 4.0)  # maxes at 4 hours

        return max(chat_staleness, delib_staleness)

    def _apply_category_floors(self, event: Event, score: float) -> float:
        """Apply minimum salience floors for certain event categories."""
        etype = event.event_type

        # Security events: floor at 0.7
        if etype in (EventType.HOME_DOOR_CHANGED, EventType.HOME_ANOMALY_DETECTED):
            now = datetime.now(USER_TZ)
            # Higher floor during quiet hours
            if now.hour >= 22 or now.hour < 6:
                return max(score, 0.85)
            return max(score, 0.7)

        # Timer completion: floor at 0.5
        if etype == EventType.TIMER_COMPLETED:
            return max(score, 0.5)

        # Rhythm deviation (daily_rhythm derived signal): modest floor so it
        # can tip deliberation when combined with other signals, never alone.
        if etype == EventType.CONTEXT_UPDATED and event.payload.get("rhythm_deviation"):
            return max(score, RHYTHM_DEVIATION_FLOOR)

        return score

    async def should_deliberate(self, user_id: str) -> bool:
        """
        Check whether accumulated salience warrants deliberation.
        Considers: threshold, rate limit, max gap, night mode.
        """
        from app.services.observation_log import get_accumulated_salience
        from app.services.working_memory import read_memory

        memory = await read_memory(user_id)
        now = datetime.now(USER_TZ)

        # Night mode: no deliberation 1-5 AM unless high-salience
        if NIGHT_HOURS[0] <= now.hour < NIGHT_HOURS[1]:
            accumulated = await get_accumulated_salience(user_id)
            # Only deliberate at night for very high salience (security events)
            return accumulated >= 4.0

        # Rate limit: min gap between deliberations
        if memory.sara_last_deliberation_at:
            try:
                last_delib = _parse_utc_iso(memory.sara_last_deliberation_at)
                minutes_since = (datetime.now(timezone.utc) - last_delib).total_seconds() / 60
                if minutes_since < MIN_DELIBERATION_GAP_MINUTES:
                    return False
            except (ValueError, TypeError):
                pass

        # Check accumulated salience threshold (runtime-tunable)
        from app.services.tunables import get_tunable_float
        salience_thresh = get_tunable_float("acs.salience_threshold", SALIENCE_THRESHOLD)
        accumulated = await get_accumulated_salience(user_id)
        if accumulated >= salience_thresh:
            return True

        # Force deliberation if too long since last one (waking hours, runtime-tunable)
        if 6 <= now.hour <= 22:
            max_gap = get_tunable_float("acs.max_deliberation_gap_hours", MAX_DELIBERATION_GAP_HOURS)
            if memory.sara_last_deliberation_at:
                try:
                    last_delib = _parse_utc_iso(memory.sara_last_deliberation_at)
                    hours_since = (datetime.now(timezone.utc) - last_delib).total_seconds() / 3600
                    if hours_since >= max_gap:
                        return True
                except (ValueError, TypeError):
                    return True  # can't parse = probably stale, deliberate
            else:
                return True  # never deliberated, do it now

        return False

    def describe_event(self, event: Event) -> str:
        """Generate a concise human-readable description of an event for the observation log."""
        etype = event.event_type
        payload = event.payload

        descriptions = {
            EventType.HOME_DOOR_CHANGED: lambda: f"Door {'opened' if payload.get('to_state') == 'on' else 'closed'}: {payload.get('friendly_name', payload.get('entity_id', 'unknown'))}",
            EventType.HOME_ANOMALY_DETECTED: lambda: f"Home anomaly: {payload.get('description', 'unusual activity detected')}",
            EventType.HOME_MOTION_DETECTED: lambda: f"Motion in {payload.get('room', payload.get('entity_id', 'unknown'))}",
            EventType.HOME_CLIMATE_CHANGED: lambda: f"Climate: {payload.get('entity_id', 'sensor')} = {payload.get('temperature', '?')}",
            EventType.HOME_LIGHT_CHANGED: lambda: f"Light {'on' if payload.get('to_state') == 'on' else 'off'}: {payload.get('friendly_name', payload.get('entity_id', 'unknown'))}",
            EventType.CHAT_MESSAGE_RECEIVED: lambda: f"David chatted: {payload.get('topic', '')[:60]}",
            EventType.FOOD_LOGGED: lambda: f"Meal logged: {payload.get('meal_type', 'food')}",
            EventType.TIMER_COMPLETED: lambda: f"Timer done: {payload.get('timer_title', 'timer')}",
            EventType.TIMER_STARTED: lambda: f"Timer started: {payload.get('timer_title', 'timer')}",
            EventType.REMINDER_CREATED: lambda: f"New reminder: {payload.get('title', '')}",
            EventType.REMINDER_COMPLETED: lambda: f"Reminder done: {payload.get('title', '')}",
            EventType.CALENDAR_EVENT_CREATED: lambda: f"New event: {payload.get('title', '')}",
            EventType.CALENDAR_EVENT_UPDATED: lambda: f"Event updated: {payload.get('title', '')}",
            EventType.NOTE_CREATED: lambda: f"Note created: {payload.get('title', '')}",
            EventType.NOTE_UPDATED: lambda: f"Note edited: {payload.get('title', '')}",
            EventType.WORKOUT_LOGGED: lambda: f"Workout: {payload.get('type', 'exercise')}",
            EventType.WORKOUT_COMPLETED: lambda: f"Workout completed: {payload.get('type', 'exercise')}",
            EventType.ACTIVITY_STATE_CHANGED: lambda: f"Activity: {payload.get('state', 'unknown')}",
            EventType.LOCATION_PLACE_ENTERED: lambda: f"David arrived at {payload.get('label', 'a place')}",
            EventType.LOCATION_PLACE_EXITED: lambda: f"David left {payload.get('label', 'a place')}",
            EventType.DESKTOP_FOCUS_SPAN: lambda: _describe_focus_span(payload),
            EventType.DESKTOP_ACTIVITY_STATE: lambda: (
                f"Desktop activity → {payload.get('state', 'unknown')}"
                + (f" (was {payload.get('previous_state')})" if payload.get('previous_state') else "")
            ),
            EventType.DESKTOP_SCREEN_CONTENT: lambda: (
                f"On screen: {(payload.get('summary') or '')[:200]}"
            ),
            EventType.GOAL_MILESTONE_REACHED: lambda: f"Milestone! {payload.get('goal_name', '')}: {payload.get('milestone', '')}",
            EventType.GOAL_COMPLETED: lambda: f"Goal completed: {payload.get('goal_name', '')}",
            EventType.HEALTH_DATA_SYNCED: lambda: f"Health data synced",
            EventType.CONTEXT_UPDATED: lambda: (
                payload.get("message", "Context updated") if payload.get("rhythm_deviation")
                else "Context updated"
            ),
        }

        formatter = descriptions.get(etype)
        if formatter:
            try:
                return formatter()
            except Exception:
                pass
        return f"{etype.value}: {str(payload)[:80]}"

    def categorize_event(self, event: Event) -> str:
        """Map event type to observation category."""
        etype = event.event_type
        categories = {
            EventType.HOME_DOOR_CHANGED: "security",
            EventType.HOME_ANOMALY_DETECTED: "security",
            EventType.HOME_MOTION_DETECTED: "home",
            EventType.HOME_CLIMATE_CHANGED: "home",
            EventType.HOME_LIGHT_CHANGED: "home",
            EventType.HOME_STATE_CHANGED: "home",
            EventType.CHAT_MESSAGE_RECEIVED: "social",
            EventType.FOOD_LOGGED: "health",
            EventType.FOOD_DELETED: "health",
            EventType.HEALTH_DATA_SYNCED: "health",
            EventType.RECOVERY_LOGGED: "health",
            EventType.WORKOUT_LOGGED: "health",
            EventType.WORKOUT_COMPLETED: "health",
            EventType.TIMER_COMPLETED: "schedule",
            EventType.TIMER_STARTED: "schedule",
            EventType.REMINDER_CREATED: "schedule",
            EventType.REMINDER_COMPLETED: "schedule",
            EventType.CALENDAR_EVENT_CREATED: "schedule",
            EventType.CALENDAR_EVENT_UPDATED: "schedule",
            EventType.NOTE_CREATED: "knowledge",
            EventType.NOTE_UPDATED: "knowledge",
            EventType.ACTIVITY_STATE_CHANGED: "activity",
            EventType.DESKTOP_FOCUS_SPAN: "activity",
            EventType.DESKTOP_ACTIVITY_STATE: "activity",
            EventType.DESKTOP_SCREEN_CONTENT: "activity",
            EventType.GOAL_MILESTONE_REACHED: "goals",
            EventType.GOAL_COMPLETED: "goals",
            EventType.GOAL_PROGRESS_LOGGED: "goals",
            EventType.CONTEXT_UPDATED: "rhythm",
        }
        return categories.get(etype, "general")


# Module-level singleton
salience_scorer = SalienceScorer()
