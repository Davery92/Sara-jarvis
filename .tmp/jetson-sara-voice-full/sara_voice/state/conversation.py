"""Conversation state machine.

States: IDLE → WAKE → LISTENING → PROCESSING → SPEAKING → COOLDOWN
With barge-in support during SPEAKING.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    IDLE = "idle"
    WAKE = "wake"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    COOLDOWN = "cooldown"


class ConversationStateMachine:
    """Main conversation state machine for voice interactions."""

    def __init__(self, config: dict):
        conv_cfg = config.get("conversation", {})
        self._wake_ms = conv_cfg.get("wake_confirmation_ms", 300)
        self._listen_timeout = conv_cfg.get("listen_timeout_seconds", 30)
        self._processing_timeout = conv_cfg.get("processing_timeout_seconds", 30)
        self._cooldown_seconds = conv_cfg.get("cooldown_seconds", 5)
        self._max_turns = conv_cfg.get("max_turns", 20)
        self._goodbye_phrases = [
            p.lower() for p in conv_cfg.get("goodbye_phrases", ["goodbye", "bye sara"])
        ]

        barge_cfg = conv_cfg.get("barge_in", {})
        self._barge_in_enabled = barge_cfg.get("enabled", True)
        self._barge_energy_threshold = barge_cfg.get("energy_threshold", 0.05)
        self._barge_min_ms = barge_cfg.get("min_duration_ms", 200)

        self._state = ConversationState.IDLE
        self._state_entered_at = time.monotonic()
        self._turn_count = 0
        self._barge_in_start: float | None = None

        # Callbacks
        self._on_state_change: list[Callable[[ConversationState, ConversationState], Awaitable[None]]] = []

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def state_duration(self) -> float:
        """Seconds spent in current state."""
        return time.monotonic() - self._state_entered_at

    def on_state_change(self, callback: Callable[[ConversationState, ConversationState], Awaitable[None]]):
        """Register a state change callback."""
        self._on_state_change.append(callback)

    async def _transition(self, new_state: ConversationState, reason: str = ""):
        """Transition to a new state."""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self._state_entered_at = time.monotonic()

        logger.info("State: %s → %s%s", old_state.value, new_state.value,
                     f" ({reason})" if reason else "")

        for callback in self._on_state_change:
            try:
                await callback(old_state, new_state)
            except Exception:
                logger.exception("State change callback error")

    async def on_wake_word(self):
        """Wake word detected — start conversation."""
        if self._state == ConversationState.IDLE:
            self._turn_count = 0
            await self._transition(ConversationState.WAKE, "wake word detected")
        elif self._state == ConversationState.COOLDOWN:
            # Re-engage during cooldown
            await self._transition(ConversationState.WAKE, "re-engagement in cooldown")

    async def on_wake_confirmation_done(self):
        """Wake confirmation sound/flash completed — start listening."""
        if self._state == ConversationState.WAKE:
            await self._transition(ConversationState.LISTENING, "confirmation done")

    async def on_speech_end(self, transcript: str = ""):
        """VAD detected end of speech — process the utterance."""
        if self._state == ConversationState.LISTENING:
            # Check for goodbye
            if self._is_goodbye(transcript):
                await self._transition(ConversationState.IDLE, f"goodbye: '{transcript}'")
                return

            self._turn_count += 1
            await self._transition(ConversationState.PROCESSING, f"turn {self._turn_count}")

    async def on_response_ready(self):
        """Backend response received — start speaking."""
        if self._state == ConversationState.PROCESSING:
            await self._transition(ConversationState.SPEAKING, "response ready")

    async def on_playback_complete(self):
        """TTS playback finished — enter cooldown."""
        if self._state == ConversationState.SPEAKING:
            if self._turn_count >= self._max_turns:
                await self._transition(ConversationState.IDLE, "max turns reached")
            else:
                await self._transition(ConversationState.COOLDOWN, "playback done")

    async def on_barge_in(self):
        """User interrupted during Sara's speech — jump to listening."""
        if self._state == ConversationState.SPEAKING and self._barge_in_enabled:
            logger.info("Barge-in detected — interrupting playback")
            await self._transition(ConversationState.LISTENING, "barge-in")

    async def on_cooldown_speech(self):
        """Speech detected during cooldown — continue conversation."""
        if self._state == ConversationState.COOLDOWN:
            await self._transition(ConversationState.LISTENING, "continued during cooldown")

    async def on_cooldown_timeout(self):
        """Cooldown period expired with no speech — return to idle."""
        if self._state == ConversationState.COOLDOWN:
            await self._transition(ConversationState.IDLE, "cooldown timeout")

    async def on_error(self, error: str = ""):
        """Error during processing — return to idle."""
        logger.error("Conversation error: %s (state=%s)", error, self._state.value)
        await self._transition(ConversationState.IDLE, f"error: {error}")

    async def check_timeouts(self):
        """Check for state timeouts. Call periodically."""
        elapsed = self.state_duration

        if self._state == ConversationState.WAKE:
            if elapsed > self._wake_ms / 1000 + 1.0:
                # Wake confirmation took too long
                await self._transition(ConversationState.LISTENING, "wake timeout")

        elif self._state == ConversationState.LISTENING:
            if elapsed > self._listen_timeout:
                await self._transition(ConversationState.IDLE, "listen timeout")

        elif self._state == ConversationState.PROCESSING:
            if elapsed > self._processing_timeout:
                await self._transition(ConversationState.IDLE, "processing timeout")

        elif self._state == ConversationState.COOLDOWN:
            if elapsed > self._cooldown_seconds:
                await self.on_cooldown_timeout()

    def check_barge_in(self, audio_rms: float) -> bool:
        """Check if audio during SPEAKING constitutes a barge-in.

        Returns True if barge-in should trigger. Caller should then
        call on_barge_in().
        """
        if self._state != ConversationState.SPEAKING or not self._barge_in_enabled:
            return False

        now = time.monotonic()

        if audio_rms >= self._barge_energy_threshold:
            if self._barge_in_start is None:
                self._barge_in_start = now
            elif (now - self._barge_in_start) * 1000 >= self._barge_min_ms:
                self._barge_in_start = None
                return True
        else:
            self._barge_in_start = None

        return False

    def _is_goodbye(self, text: str) -> bool:
        """Check if the transcript is a goodbye phrase."""
        text_lower = text.lower().strip()
        return any(phrase in text_lower for phrase in self._goodbye_phrases)

    async def force_idle(self, reason: str = "forced"):
        """Force return to idle state."""
        await self._transition(ConversationState.IDLE, reason)
