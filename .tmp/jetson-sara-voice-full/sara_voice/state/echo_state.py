"""Echo state tracking to prevent self-triggering.

Layered on top of conversation state machine:
QUIET → SARA_SPEAKING → TAIL_SUPPRESSION(500ms) → QUIET

Suppresses wake word detection and STT during Sara's audio playback
to prevent echo-triggered activations.
"""

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class EchoPhase(Enum):
    QUIET = "quiet"
    SARA_SPEAKING = "sara_speaking"
    TAIL_SUPPRESSION = "tail_suppression"


class EchoStateTracker:
    """Tracks Sara's speech output to suppress echo-triggered activations."""

    def __init__(self, config: dict):
        echo_cfg = config.get("echo", {})
        self._tail_ms = echo_cfg.get("tail_suppression_ms", 500)

        self._phase = EchoPhase.QUIET
        self._speaking_start: float | None = None
        self._speaking_end: float | None = None

    @property
    def phase(self) -> EchoPhase:
        return self._phase

    @property
    def should_suppress_wake_word(self) -> bool:
        """Whether wake word detection should be suppressed."""
        self._update()
        return self._phase != EchoPhase.QUIET

    @property
    def should_suppress_stt(self) -> bool:
        """Whether STT should be suppressed."""
        self._update()
        return self._phase != EchoPhase.QUIET

    def on_playback_start(self):
        """Sara started speaking (TTS audio playing)."""
        self._phase = EchoPhase.SARA_SPEAKING
        self._speaking_start = time.monotonic()
        self._speaking_end = None
        logger.debug("Echo state: SARA_SPEAKING")

    def on_playback_stop(self):
        """Sara stopped speaking (TTS audio finished)."""
        if self._phase == EchoPhase.SARA_SPEAKING:
            self._phase = EchoPhase.TAIL_SUPPRESSION
            self._speaking_end = time.monotonic()
            logger.debug("Echo state: TAIL_SUPPRESSION")

    def _update(self):
        """Update phase based on timing."""
        if self._phase == EchoPhase.TAIL_SUPPRESSION and self._speaking_end is not None:
            elapsed_ms = (time.monotonic() - self._speaking_end) * 1000
            if elapsed_ms >= self._tail_ms:
                self._phase = EchoPhase.QUIET
                self._speaking_end = None
                logger.debug("Echo state: QUIET (tail expired)")

    def reset(self):
        """Reset to quiet state."""
        self._phase = EchoPhase.QUIET
        self._speaking_start = None
        self._speaking_end = None
