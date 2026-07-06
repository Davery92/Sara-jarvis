"""Push transcripts to Sara backend's cognitive raw buffer.

Sends voice transcripts to /api/cognitive/raw-buffer/audio
for consolidation and memory formation.
"""

import logging

logger = logging.getLogger(__name__)


class RawBufferClient:
    """Pushes audio transcripts to Sara's raw buffer for cognitive processing."""

    def __init__(self, config: dict, backend_client):
        backend_cfg = config.get("backend", {})
        self._endpoint = backend_cfg.get("raw_buffer_endpoint", "/api/cognitive/raw-buffer/audio")
        self._audio_endpoint = "/api/cognitive/audio/processed"
        self._backend = backend_client

    async def push_transcript(
        self,
        text: str,
        source: str = "jetson_voice",
        speaker: str = "david",
        diarization: dict | None = None,
        sara_response: str | None = None,
        duration_seconds: float = 0.0,
    ) -> bool:
        """Push a transcript to the raw buffer.

        Args:
            text: Transcribed text
            source: Source identifier
            speaker: Primary speaker identifier
            diarization: Optional diarization metadata
            sara_response: Optional Sara response for paired transcript logging
            duration_seconds: Duration of the audio segment
        """
        if not text.strip():
            return False

        # Preferred path: structured audio endpoint (lands in raw_buffer:audio).
        audio_data = {
            "transcript": text,
            "speaker": speaker,
            "duration_seconds": duration_seconds,
            "source": source,
            "diarization": diarization or {},
            "metadata": {
                "sara_response": sara_response or "",
            },
        }

        success = await self._backend.send_event(self._audio_endpoint, audio_data)
        if success:
            logger.debug(
                "Transcript pushed to audio stream: '%s...' (duration=%.2fs, speaker=%s)",
                text[:50],
                duration_seconds,
                speaker,
            )
            return True

        # Fallback path for older backends.
        legacy_data = {
            "user_text": text,
            "source": source,
        }
        if sara_response:
            legacy_data["sara_response"] = sara_response

        success = await self._backend.send_event(self._endpoint, legacy_data)
        if success:
            logger.debug(
                "Transcript pushed via legacy raw buffer endpoint: '%s...' (duration=%.2fs)",
                text[:50],
                duration_seconds,
            )
        else:
            logger.warning("Failed to push transcript to raw buffer")
        return success
