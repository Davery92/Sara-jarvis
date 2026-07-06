"""Speaker verification client using NeMo verify-upload endpoint.

Provides utterance-level speaker attribution (David vs unknown) for
raw-buffer transcript metadata.
"""

import io
import logging
import struct
import time

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class SpeakerVerificationClient:
    """Verify whether an utterance matches David's enrolled voice."""

    def __init__(self, config: dict):
        verify_cfg = config.get("speaker_verification", {})
        self._enabled = verify_cfg.get("enabled", True)
        self._base_url = verify_cfg.get("url", "http://10.185.1.8:8002")
        self._endpoint = verify_cfg.get("endpoint", "/verify-upload")
        self._speaker_id = verify_cfg.get("speaker_id", "david")
        self._threshold = float(verify_cfg.get("threshold", 0.6))
        self._timeout_seconds = float(verify_cfg.get("timeout_seconds", 6.0))
        self._sample_rate = int(config.get("audio", {}).get("target_rate", 16000))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._client

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert float32 mono audio [-1, 1] to WAV bytes."""
        pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = pcm16.tobytes()

        channels = 1
        sample_width = 2
        byte_rate = self._sample_rate * channels * sample_width
        block_align = channels * sample_width
        data_size = len(pcm_bytes)

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            self._sample_rate,
            byte_rate,
            block_align,
            sample_width * 8,
            b"data",
            data_size,
        )
        return header + pcm_bytes

    async def verify(self, audio: np.ndarray, timeout_override: float | None = None) -> dict:
        """Verify speaker identity from utterance audio.

        `timeout_override` lets latency-sensitive callers (barge-in, B2.3)
        use a much tighter budget than the default utterance-level check —
        a slow verify there should be skipped, not block the interrupt.
        """
        if not self._enabled:
            return {
                "enabled": False,
                "speaker_id": self._speaker_id,
                "is_match": True,
                "confidence": 1.0,
            }
        if len(audio) == 0:
            return {
                "enabled": True,
                "speaker_id": self._speaker_id,
                "is_match": False,
                "confidence": 0.0,
                "error": "empty_audio",
            }

        client = await self._get_client()
        wav_bytes = self._audio_to_wav_bytes(audio)

        started = time.monotonic()
        try:
            response = await client.post(
                f"{self._base_url}{self._endpoint}",
                data={
                    "speaker_id": self._speaker_id,
                    "threshold": str(self._threshold),
                },
                files={
                    "file": ("utterance.wav", io.BytesIO(wav_bytes), "audio/wav"),
                },
                timeout=timeout_override if timeout_override is not None else self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            payload.setdefault("speaker_id", self._speaker_id)
            payload.setdefault("is_match", False)
            payload.setdefault("confidence", 0.0)
            payload["latency_seconds"] = round(time.monotonic() - started, 3)
            return payload
        except Exception as e:
            logger.warning("Speaker verification failed: %s", e)
            return {
                "enabled": True,
                "speaker_id": self._speaker_id,
                "is_match": False,
                "confidence": 0.0,
                "error": str(e),
                "latency_seconds": round(time.monotonic() - started, 3),
            }

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
