"""Report face/presence/voice events to Sara backend sensory endpoints.

Pushes vision and voice events to:
- /api/sensory/vision/face-detected
- /api/sensory/vision/presence-changed
- /api/sensory/voice/conversation-started
- /api/sensory/voice/conversation-ended
"""

import logging
import time

logger = logging.getLogger(__name__)


class EventReporter:
    """Reports sensory events to Sara backend."""

    def __init__(self, config: dict, backend_client):
        backend_cfg = config.get("backend", {})
        self._sensory_base = backend_cfg.get("sensory_base", "/api/sensory")
        self._backend = backend_client

    async def report_face_detected(self, is_david: bool, confidence: float, similarity: float):
        """Report a face detection to backend."""
        return await self._backend.send_event(
            f"{self._sensory_base}/vision/face-detected",
            {
                "is_david": is_david,
                "confidence": confidence,
                "similarity": similarity,
                "source": "jetson_obsbot",
                "timestamp": time.time(),
            },
        )

    async def report_presence_changed(self, state: str, reason: str = ""):
        """Report desk presence change to backend."""
        return await self._backend.send_event(
            f"{self._sensory_base}/vision/presence-changed",
            {
                "state": state,  # "present", "absent", "unknown"
                "reason": reason,
                "source": "jetson_obsbot",
                "timestamp": time.time(),
            },
        )

    async def report_conversation_started(self):
        """Report voice conversation start to backend."""
        return await self._backend.send_event(
            f"{self._sensory_base}/voice/conversation-started",
            {
                "source": "jetson_voice",
                "timestamp": time.time(),
            },
        )

    async def report_conversation_ended(self, turns: int, duration_seconds: float, summary: str = ""):
        """Report voice conversation end to backend."""
        return await self._backend.send_event(
            f"{self._sensory_base}/voice/conversation-ended",
            {
                "turns": turns,
                "duration_seconds": duration_seconds,
                "summary": summary,
                "source": "jetson_voice",
                "timestamp": time.time(),
            },
        )

    async def report_health(self, health_data: dict):
        """Report Jetson health to backend."""
        return await self._backend.send_event(
            f"{self._sensory_base}/jetson/health",
            health_data,
        )
