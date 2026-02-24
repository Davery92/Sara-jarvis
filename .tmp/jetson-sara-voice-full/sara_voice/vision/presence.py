"""Desk presence state machine.

Tracks whether David is at his desk based on face detection events.
States: PRESENT, ABSENT, UNKNOWN

Debounces transitions to avoid flicker from missed detections.
"""

import logging
import time
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class PresenceState(Enum):
    UNKNOWN = "unknown"
    PRESENT = "present"
    ABSENT = "absent"


class DeskPresence:
    """Tracks desk occupancy using face detection events."""

    def __init__(self, config: dict):
        presence_cfg = config.get("vision", {}).get("presence", {})
        self._absent_timeout = presence_cfg.get("absent_timeout_seconds", 60)
        self._present_cooldown = presence_cfg.get("present_cooldown_seconds", 10)

        self._state = PresenceState.UNKNOWN
        self._last_face_time: float | None = None
        self._last_state_change: float = 0
        self._david_seen_count = 0

        # Callbacks
        self._on_change: list[Callable[[PresenceState, PresenceState], Awaitable[None]]] = []

    @property
    def state(self) -> PresenceState:
        return self._state

    @property
    def seconds_since_last_face(self) -> float | None:
        """Seconds since David was last detected, or None if never."""
        if self._last_face_time is None:
            return None
        return time.monotonic() - self._last_face_time

    def on_change(self, callback: Callable[[PresenceState, PresenceState], Awaitable[None]]):
        """Register a presence change callback."""
        self._on_change.append(callback)

    async def on_face_detected(self, is_david: bool):
        """Called when a face is detected in a frame."""
        now = time.monotonic()

        if is_david:
            self._last_face_time = now
            self._david_seen_count += 1

            if self._state != PresenceState.PRESENT:
                await self._transition(PresenceState.PRESENT, "David face detected")

    async def update(self):
        """Check for timeout-based transitions. Call periodically."""
        if self._state == PresenceState.PRESENT and self._last_face_time is not None:
            elapsed = time.monotonic() - self._last_face_time
            if elapsed >= self._absent_timeout:
                await self._transition(
                    PresenceState.ABSENT,
                    f"no face for {elapsed:.0f}s",
                )

    async def _transition(self, new_state: PresenceState, reason: str):
        """Transition to a new state with debouncing."""
        old_state = self._state
        if old_state == new_state:
            return

        now = time.monotonic()
        # Debounce: don't flip back too quickly
        if old_state == PresenceState.PRESENT and new_state == PresenceState.ABSENT:
            pass  # absent_timeout already provides debouncing
        elif old_state == PresenceState.ABSENT and new_state == PresenceState.PRESENT:
            if now - self._last_state_change < self._present_cooldown:
                return  # Too soon to flip back

        self._state = new_state
        self._last_state_change = now

        logger.info("Presence: %s → %s (%s)", old_state.value, new_state.value, reason)

        for callback in self._on_change:
            try:
                await callback(old_state, new_state)
            except Exception:
                logger.exception("Presence change callback error")

    def reset(self):
        """Reset to unknown state."""
        self._state = PresenceState.UNKNOWN
        self._last_face_time = None
        self._david_seen_count = 0
