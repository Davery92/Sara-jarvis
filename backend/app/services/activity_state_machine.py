"""
Activity State Machine — Sara's Awareness of What David Is Doing

Maintains a running model of David's current activity based on signals from:
- Home Assistant (motion sensors, device states, media players)
- Calendar events (meetings, scheduled activities)
- Time of day + historical patterns
- Interaction recency (last chat, last app open)
- Body state (sleep, meals)

The activity state drives the interruptibility model, which controls
how and when Sara delivers notifications and takes autonomous actions.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

USER_TZ = ZoneInfo("America/New_York")


class ActivityState(str, Enum):
    """David's current primary activity."""
    SLEEPING = "sleeping"
    WAKING = "waking"               # Just woke up, first 30 min
    MORNING_ROUTINE = "morning_routine"  # First 1-2 hours
    ACTIVE = "active"               # General awake, no specific focus
    FOCUSED_WORK = "focused_work"   # Deep work at desk
    IN_MEETING = "in_meeting"       # Calendar event marked as meeting
    EXERCISING = "exercising"       # At gym or working out
    COOKING = "cooking"             # In kitchen, active
    WINDING_DOWN = "winding_down"   # Evening, pre-sleep
    AWAY = "away"                   # Left the house
    UNKNOWN = "unknown"


# Interruptibility defaults per state (0.0 = never interrupt, 1.0 = always ok)
STATE_INTERRUPTIBILITY = {
    ActivityState.SLEEPING: 0.0,
    ActivityState.WAKING: 0.4,
    ActivityState.MORNING_ROUTINE: 0.5,
    ActivityState.ACTIVE: 0.8,
    ActivityState.FOCUSED_WORK: 0.2,
    ActivityState.IN_MEETING: 0.1,
    ActivityState.EXERCISING: 0.3,
    ActivityState.COOKING: 0.5,
    ActivityState.WINDING_DOWN: 0.4,
    ActivityState.AWAY: 0.6,
    ActivityState.UNKNOWN: 0.5,
}

# How long each state persists without reinforcing signals before decaying to ACTIVE/UNKNOWN
STATE_DECAY_MINUTES = {
    ActivityState.SLEEPING: 600,        # 10 hours max
    ActivityState.WAKING: 30,
    ActivityState.MORNING_ROUTINE: 120,
    ActivityState.FOCUSED_WORK: 180,    # 3 hours then check
    ActivityState.IN_MEETING: 180,      # Max meeting length
    ActivityState.EXERCISING: 120,
    ActivityState.COOKING: 90,
    ActivityState.WINDING_DOWN: 180,
    ActivityState.AWAY: 720,            # 12 hours max
}


@dataclass
class ActivitySignal:
    """An input signal that may cause a state transition."""
    signal_type: str        # motion, calendar, interaction, time, device, media
    source: str             # entity_id or system name
    value: str              # on/off, event_name, etc.
    timestamp: datetime = field(default_factory=lambda: datetime.now(USER_TZ))
    metadata: Dict = field(default_factory=dict)


@dataclass
class ActivitySnapshot:
    """Current activity state with metadata."""
    state: ActivityState = ActivityState.UNKNOWN
    confidence: float = 0.5         # 0-1, how sure we are
    since: Optional[datetime] = None  # When this state started
    reason: str = ""                # Why we think this
    room: Optional[str] = None      # Which room (if known)
    interruptibility: float = 0.5   # Computed score
    signals: List[str] = field(default_factory=list)  # Recent signals that informed this

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['state'] = self.state.value
        if self.since:
            d['since'] = self.since.isoformat()
        return d

    def age_minutes(self) -> float:
        """How many minutes we've been in this state."""
        if not self.since:
            return 0.0
        now = datetime.now(USER_TZ)
        return (now - self.since).total_seconds() / 60


class ActivityStateMachine:
    """
    Maintains David's current activity state and processes incoming signals.

    Design:
    - Signals arrive from HA events, calendar, interactions, and time
    - Each signal is evaluated against transition rules
    - State has a confidence that decays over time without reinforcement
    - Multiple weak signals can combine to suggest a state
    """

    def __init__(self):
        self._current = ActivitySnapshot(
            state=ActivityState.UNKNOWN,
            confidence=0.3,
            since=datetime.now(USER_TZ),
            reason="initial state",
        )
        # Room motion tracking: room_name -> last_motion_at
        self._room_motion: Dict[str, datetime] = {}
        # Recent signals buffer for reasoning
        self._recent_signals: List[ActivitySignal] = []
        self._max_signal_buffer = 50
        # Pending state change events for event bus publishing
        self._pending_events: List[Dict] = []

    @property
    def current(self) -> ActivitySnapshot:
        """Get current state, applying time-based decay."""
        self._apply_decay()
        self._current.interruptibility = STATE_INTERRUPTIBILITY.get(
            self._current.state, 0.5
        )
        return self._current

    def process_signal(self, signal: ActivitySignal) -> ActivitySnapshot:
        """
        Process an incoming signal and potentially transition state.

        Returns the (possibly updated) current state.
        """
        self._buffer_signal(signal)

        if signal.signal_type == "motion":
            self._handle_motion(signal)
        elif signal.signal_type == "calendar":
            self._handle_calendar(signal)
        elif signal.signal_type == "interaction":
            self._handle_interaction(signal)
        elif signal.signal_type == "time":
            self._handle_time(signal)
        elif signal.signal_type == "device":
            self._handle_device(signal)
        elif signal.signal_type == "media":
            self._handle_media(signal)
        elif signal.signal_type == "sleep":
            self._handle_sleep(signal)
        elif signal.signal_type == "workout":
            self._handle_workout(signal)
        elif signal.signal_type == "face":
            self._handle_face(signal)
        elif signal.signal_type == "desk_presence":
            self._handle_desk_presence(signal)

        return self.current

    def compute_from_full_context(
        self,
        now: datetime,
        calendar_events: List[Dict],
        last_interaction_at: Optional[datetime],
        body_state: Optional[Dict],
        ha_recent_activity: List[Dict],
        first_activity_today: Optional[datetime],
        has_chatted_today: bool,
    ) -> ActivitySnapshot:
        """
        Full recomputation from all available context.
        Called by the subconscious worker each cycle.
        """
        candidates: List[Tuple[ActivityState, float, str]] = []

        hour = now.hour
        minute = now.minute
        time_decimal = hour + minute / 60.0

        # --- Time-based priors ---
        # David is typically awake by 6 AM — only assume sleeping before 5 AM
        if time_decimal < 5.0:
            candidates.append((ActivityState.SLEEPING, 0.7, "it's before 5am"))
        elif 5.0 <= time_decimal < 7.0 and not first_activity_today:
            # Morning window — David is usually awake, just hasn't chatted yet
            candidates.append((ActivityState.ACTIVE, 0.4, "morning — likely awake"))
        elif time_decimal >= 23.0:
            candidates.append((ActivityState.SLEEPING, 0.5, "it's after 11pm"))
            candidates.append((ActivityState.WINDING_DOWN, 0.4, "late evening"))
        elif time_decimal >= 21.0:
            candidates.append((ActivityState.WINDING_DOWN, 0.5, "evening wind-down time"))

        # --- First activity detection (waking) ---
        if first_activity_today:
            minutes_since_first = (now - first_activity_today).total_seconds() / 60
            if minutes_since_first < 30:
                candidates.append((ActivityState.WAKING, 0.7, f"first activity {int(minutes_since_first)}m ago"))
            elif minutes_since_first < 120:
                candidates.append((ActivityState.MORNING_ROUTINE, 0.5, f"morning routine ({int(minutes_since_first)}m since waking)"))

        # --- Calendar-based detection ---
        for event in calendar_events:
            start = event.get("start")
            end = event.get("end")
            title = (event.get("title") or event.get("summary") or "").lower()

            if not start or not end:
                continue

            # Parse if string
            if isinstance(start, str):
                try:
                    start = datetime.fromisoformat(start)
                except (ValueError, TypeError):
                    continue
            if isinstance(end, str):
                try:
                    end = datetime.fromisoformat(end)
                except (ValueError, TypeError):
                    continue

            # Ensure timezone aware
            if start.tzinfo is None:
                start = start.replace(tzinfo=USER_TZ)
            if end.tzinfo is None:
                end = end.replace(tzinfo=USER_TZ)

            # Is this event happening now?
            if start <= now <= end:
                # Classify event type
                if any(kw in title for kw in ["gym", "workout", "exercise", "gymnastics", "training", "crossfit"]):
                    candidates.append((ActivityState.EXERCISING, 0.85, f"calendar: {title}"))
                elif any(kw in title for kw in ["meeting", "call", "standup", "sync", "1:1", "interview"]):
                    candidates.append((ActivityState.IN_MEETING, 0.85, f"calendar: {title}"))
                else:
                    # Generic scheduled event — slight boost to ACTIVE
                    candidates.append((ActivityState.ACTIVE, 0.5, f"calendar event: {title}"))

            # Event starting within 10 min
            elif timedelta(0) < (start - now) < timedelta(minutes=10):
                if any(kw in title for kw in ["gym", "workout", "exercise", "gymnastics"]):
                    candidates.append((ActivityState.ACTIVE, 0.5, f"gym in {int((start-now).total_seconds()/60)}m"))

        # --- HA activity-based detection ---
        recent_motion_rooms: Dict[str, datetime] = {}
        for activity in ha_recent_activity:
            entity_id = activity.get("entity_id", "")
            to_state = activity.get("to_state", "")
            changed_at = activity.get("changed_at")

            if isinstance(changed_at, str):
                try:
                    changed_at = datetime.fromisoformat(changed_at)
                except (ValueError, TypeError):
                    continue

            if changed_at and changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=USER_TZ)

            # Motion sensors
            if "binary_sensor" in entity_id and to_state == "on":
                room = self._entity_to_room(entity_id)
                if room and changed_at:
                    if room not in recent_motion_rooms or changed_at > recent_motion_rooms[room]:
                        recent_motion_rooms[room] = changed_at

            # Media player activity
            if "media_player" in entity_id and to_state == "playing":
                room = self._entity_to_room(entity_id)
                if room:
                    candidates.append((ActivityState.ACTIVE, 0.4, f"media playing in {room}"))

        # Analyze room motion
        # IMPORTANT: Motion sensors can't distinguish between household members
        # (David, Amanda, kids, dogs). Motion is only a weak signal of "someone
        # is home" — NOT a reliable indicator of what David specifically is doing.
        # Only use motion for: house-occupied (yes/no) and absence detection.
        if recent_motion_rooms:
            latest_room = max(recent_motion_rooms, key=recent_motion_rooms.get)
            latest_time = recent_motion_rooms[latest_room]
            minutes_ago = (now - latest_time).total_seconds() / 60

            if minutes_ago < 30:
                self._room_motion[latest_room] = latest_time
                # Motion detected = someone is home, but we can't know it's David.
                # Only use as weak "not away" signal, not for room-specific activities.
                candidates.append((ActivityState.ACTIVE, 0.25, f"motion in {latest_room} {int(minutes_ago)}m ago"))

            # No motion anywhere for 90+ minutes during waking hours = probably nobody home
            if minutes_ago > 90 and 6 <= hour < 23:
                candidates.append((ActivityState.AWAY, 0.3, f"no motion for {int(minutes_ago)}m"))

        # --- Interaction recency ---
        if last_interaction_at:
            if last_interaction_at.tzinfo is None:
                last_interaction_at = last_interaction_at.replace(tzinfo=USER_TZ)
            hours_since = (now - last_interaction_at).total_seconds() / 3600
            if hours_since < 0.1:  # Within 6 minutes
                # Recent interaction reinforces ACTIVE or FOCUSED_WORK
                candidates.append((ActivityState.ACTIVE, 0.4, f"chatted {int(hours_since*60)}m ago"))

        # --- Body state signals ---
        if body_state:
            alertness = body_state.get("alertness", 0.5)
            if alertness < 0.2 and hour >= 21:
                candidates.append((ActivityState.SLEEPING, 0.4, "very low alertness at night"))
                candidates.append((ActivityState.WINDING_DOWN, 0.5, "very low alertness"))

        # --- Pick the best candidate ---
        if not candidates:
            # No signals — keep current state with decayed confidence
            self._apply_decay()
            return self.current

        # Sort by confidence descending
        candidates.sort(key=lambda c: c[1], reverse=True)
        best_state, best_confidence, best_reason = candidates[0]

        # Hysteresis: current state gets a bonus to prevent flapping
        current_state = self._current.state
        if current_state != ActivityState.UNKNOWN:
            for state, conf, reason in candidates:
                if state == current_state:
                    # Boost current state by 0.15 for stability
                    boosted_conf = min(conf + 0.15, 1.0)
                    if boosted_conf > best_confidence:
                        best_state = state
                        best_confidence = boosted_conf
                        best_reason = f"{reason} (continuing)"
                    break

        # Transition if new state wins
        if best_state != current_state:
            logger.info(
                f"Activity transition: {current_state.value} -> {best_state.value} "
                f"(confidence={best_confidence:.2f}, reason={best_reason})"
            )
            self._current = ActivitySnapshot(
                state=best_state,
                confidence=best_confidence,
                since=now,
                reason=best_reason,
                room=self._get_current_room(),
                signals=[f"{s}: {r}" for s, _, r in candidates[:3]],
            )
        else:
            # Reinforce current state
            self._current.confidence = max(self._current.confidence, best_confidence)
            self._current.reason = best_reason
            self._current.room = self._get_current_room()

        self._current.interruptibility = STATE_INTERRUPTIBILITY.get(best_state, 0.5)
        return self._current

    # --- Signal handlers ---

    def _handle_motion(self, signal: ActivitySignal):
        """Handle motion sensor events from HA.

        NOTE: Motion sensors can't distinguish household members (David, Amanda,
        kids, dogs). We only use motion as a weak occupancy signal, never to
        infer David's specific activity or room.
        """
        room = signal.metadata.get("room") or self._entity_to_room(signal.source)
        if room:
            self._room_motion[room] = signal.timestamp

    def _handle_calendar(self, signal: ActivitySignal):
        """Handle calendar event start/end."""
        if signal.value == "meeting_start":
            title = signal.metadata.get("title", "meeting")
            if any(kw in title.lower() for kw in ["gym", "workout", "exercise", "gymnastics"]):
                self._transition(ActivityState.EXERCISING, 0.85, f"calendar: {title}")
            else:
                self._transition(ActivityState.IN_MEETING, 0.85, f"calendar: {title}")
        elif signal.value == "meeting_end":
            self._transition(ActivityState.ACTIVE, 0.6, "meeting ended")

    def _handle_interaction(self, signal: ActivitySignal):
        """Handle Sara interaction (chat message, app open)."""
        current = self._current.state
        if current == ActivityState.SLEEPING:
            self._transition(ActivityState.WAKING, 0.8, "David interacted with Sara")
        elif current == ActivityState.AWAY:
            self._transition(ActivityState.ACTIVE, 0.7, "David is chatting — must be back")
        # Reinforce current active state
        if current in (ActivityState.ACTIVE, ActivityState.FOCUSED_WORK, ActivityState.MORNING_ROUTINE):
            self._current.confidence = min(self._current.confidence + 0.1, 1.0)

    def _handle_time(self, signal: ActivitySignal):
        """Handle time-of-day transitions (called periodically)."""
        hour = signal.timestamp.hour
        current = self._current.state

        if hour >= 23 and current not in (ActivityState.SLEEPING,):
            self._transition(ActivityState.WINDING_DOWN, 0.5, "it's past 11pm")
        elif hour < 5 and current != ActivityState.SLEEPING:
            self._transition(ActivityState.SLEEPING, 0.6, "it's the middle of the night")

    def _handle_device(self, signal: ActivitySignal):
        """Handle device state changes (computer on/off, TV, etc.)."""
        entity = signal.source.lower()
        if "computer" in entity or "workstation" in entity:
            if signal.value == "on":
                self._transition(ActivityState.FOCUSED_WORK, 0.5, "computer turned on")
            elif signal.value == "off" and self._current.state == ActivityState.FOCUSED_WORK:
                self._transition(ActivityState.ACTIVE, 0.5, "computer turned off")

    def _handle_media(self, signal: ActivitySignal):
        """Handle media player events."""
        if signal.value == "playing":
            current = self._current.state
            if current == ActivityState.WINDING_DOWN:
                pass  # Keep winding down — watching something before bed
            elif current != ActivityState.IN_MEETING:
                # Media playing suggests relaxing / active
                self._current.confidence = max(self._current.confidence, 0.5)

    def _handle_sleep(self, signal: ActivitySignal):
        """Handle sleep tracking signals (from health data)."""
        if signal.value == "sleep_start":
            self._transition(ActivityState.SLEEPING, 0.9, "sleep tracking started")
        elif signal.value == "sleep_end":
            self._transition(ActivityState.WAKING, 0.9, "sleep tracking ended")

    def _handle_workout(self, signal: ActivitySignal):
        """Handle workout start/end."""
        if signal.value == "start":
            self._transition(ActivityState.EXERCISING, 0.9, f"workout started: {signal.metadata.get('type', 'exercise')}")
        elif signal.value == "end":
            self._transition(ActivityState.ACTIVE, 0.7, "workout finished")

    def _handle_face(self, signal: ActivitySignal):
        """Handle face detection events from Jetson vision system."""
        is_david = signal.metadata.get("is_david", False)
        if is_david:
            current = self._current.state
            # David at desk → reinforce ACTIVE or FOCUSED_WORK
            if current == ActivityState.AWAY:
                self._transition(ActivityState.ACTIVE, 0.7, "David seen at desk")
            elif current in (ActivityState.ACTIVE, ActivityState.FOCUSED_WORK):
                self._current.confidence = min(self._current.confidence + 0.05, 1.0)
            elif current == ActivityState.UNKNOWN:
                self._transition(ActivityState.ACTIVE, 0.6, "David seen at desk")

    def _handle_desk_presence(self, signal: ActivitySignal):
        """Handle desk presence state changes from Jetson vision system."""
        state = signal.value  # "present", "absent", "unknown"
        if state == "absent":
            current = self._current.state
            if current in (ActivityState.FOCUSED_WORK, ActivityState.ACTIVE):
                # Don't immediately transition to AWAY — just lower confidence
                self._current.confidence = max(self._current.confidence - 0.2, 0.2)
                self._current.reason = "left desk"
        elif state == "present":
            current = self._current.state
            if current == ActivityState.AWAY:
                self._transition(ActivityState.ACTIVE, 0.7, "returned to desk")

    # --- Internal helpers ---

    def _transition(self, new_state: ActivityState, confidence: float, reason: str, room: str = None):
        """Execute a state transition."""
        old = self._current.state
        if old == new_state:
            # Reinforce
            self._current.confidence = max(self._current.confidence, confidence)
            self._current.reason = reason
            return

        current_room = room or self._get_current_room()
        logger.info(f"Activity: {old.value} -> {new_state.value} ({reason})")

        # Record event for event bus publishing
        self._pending_events.append({
            "old": old.value,
            "new": new_state.value,
            "confidence": confidence,
            "reason": reason,
            "room": current_room,
        })

        self._current = ActivitySnapshot(
            state=new_state,
            confidence=confidence,
            since=datetime.now(USER_TZ),
            reason=reason,
            room=current_room,
            interruptibility=STATE_INTERRUPTIBILITY.get(new_state, 0.5),
        )

    def drain_pending_events(self) -> List[Dict]:
        """Return and clear pending state change events."""
        events = self._pending_events
        self._pending_events = []
        return events

    def _apply_decay(self):
        """Decay confidence over time. If state has been held too long without
        reinforcement, fall back to UNKNOWN."""
        if not self._current.since:
            return

        age_min = self._current.age_minutes()
        max_age = STATE_DECAY_MINUTES.get(self._current.state, 120)

        if age_min > max_age:
            # State has expired — decay to ACTIVE (daytime) or UNKNOWN
            hour = datetime.now(USER_TZ).hour
            if 6 <= hour < 22:
                fallback = ActivityState.ACTIVE
            else:
                fallback = ActivityState.UNKNOWN
            if self._current.state != fallback:
                logger.info(f"Activity decay: {self._current.state.value} -> {fallback.value} "
                           f"(no reinforcement for {int(age_min)}m)")
                self._current.state = fallback
                self._current.confidence = 0.3
                self._current.reason = f"decayed after {int(age_min)}m without reinforcement"
        elif age_min > max_age * 0.5:
            # Halfway to decay — start lowering confidence
            decay_factor = 1.0 - ((age_min - max_age * 0.5) / (max_age * 0.5)) * 0.3
            self._current.confidence = max(0.2, self._current.confidence * decay_factor)

    def _entity_to_room(self, entity_id: str) -> Optional[str]:
        """Extract room name from HA entity ID.
        Examples:
            binary_sensor.office_motion -> office
            binary_sensor.kitchen_occupancy -> kitchen
            light.living_room_lamp -> living_room
        """
        parts = entity_id.split(".", 1)
        if len(parts) < 2:
            return None

        name = parts[1].lower()

        # Common room patterns
        room_keywords = [
            "office", "kitchen", "bedroom", "bathroom", "living_room",
            "living", "garage", "basement", "attic", "hallway",
            "dining", "den", "studio", "gym", "laundry",
        ]

        for room in room_keywords:
            if room in name:
                return room

        # Fall back to first part of entity name before _motion, _occupancy, etc.
        for suffix in ["_motion", "_occupancy", "_presence", "_sensor", "_lamp", "_light"]:
            if suffix in name:
                return name.split(suffix)[0].replace("_", " ").strip()

        return None

    def _get_current_room(self) -> Optional[str]:
        """Motion sensors can't tell who's moving — don't report a room for David."""
        return None

    def _buffer_signal(self, signal: ActivitySignal):
        """Buffer recent signals for debugging."""
        self._recent_signals.append(signal)
        if len(self._recent_signals) > self._max_signal_buffer:
            self._recent_signals.pop(0)

    def restore_state(self, state_dict: Dict):
        """Restore state from database (e.g., after restart)."""
        try:
            self._current = ActivitySnapshot(
                state=ActivityState(state_dict.get("state", "unknown")),
                confidence=state_dict.get("confidence", 0.3),
                since=datetime.fromisoformat(state_dict["since"]) if state_dict.get("since") else datetime.now(USER_TZ),
                reason=state_dict.get("reason", "restored from db"),
                room=state_dict.get("room"),
                interruptibility=state_dict.get("interruptibility", 0.5),
            )
            logger.info(f"Restored activity state: {self._current.state.value}")
        except Exception as e:
            logger.error(f"Failed to restore activity state: {e}")


# Global singleton
activity_state_machine = ActivityStateMachine()
