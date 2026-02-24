"""Speech-to-Text: Remote Whisper API + local whisper.cpp fallback.

Primary: GPU cluster Whisper at 10.185.1.8:8585
Fallback: Local whisper.cpp base.en CUDA on Jetson
"""

import io
import logging
import time

import numpy as np

logger = logging.getLogger(__name__)


class STTClient:
    """Speech-to-text with remote API and local fallback."""

    def __init__(self, config: dict):
        stt_cfg = config.get("stt", {})
        self._remote_url = stt_cfg.get("remote_url", "http://10.185.1.8:8585/v1/audio/transcriptions")
        self._remote_timeout = stt_cfg.get("remote_timeout_seconds", 10)
        self._remote_retries = int(stt_cfg.get("remote_retries", 1))
        self._local_model_path = stt_cfg.get("local_model_path", "models/ggml-base.en.bin")
        self._local_threads = stt_cfg.get("local_threads", 4)
        self._language = stt_cfg.get("language", "en")
        self._use_local_fallback = stt_cfg.get("use_local_fallback", True)

        self._sample_rate = config.get("audio", {}).get("target_rate", 16000)
        self._local_model = None
        self._http_client = None

    async def _get_client(self):
        """Lazy-init async HTTP client."""
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=self._remote_timeout)
        return self._http_client

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert float32 PCM to WAV bytes for API upload."""
        import struct

        # Convert float32 [-1, 1] to int16
        pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = pcm16.tobytes()

        # Build WAV header
        data_size = len(pcm_bytes)
        channels = 1
        sample_width = 2  # 16-bit
        byte_rate = self._sample_rate * channels * sample_width
        block_align = channels * sample_width

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,  # fmt chunk size
            1,   # PCM format
            channels,
            self._sample_rate,
            byte_rate,
            block_align,
            sample_width * 8,  # bits per sample
            b"data",
            data_size,
        )

        return header + pcm_bytes

    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio. Tries remote first, falls back to local."""
        if len(audio) == 0:
            return ""

        start = time.monotonic()

        # Try remote first
        last_remote_error = None
        for attempt in range(max(self._remote_retries, 0) + 1):
            try:
                text = await self._transcribe_remote(audio)
                elapsed = time.monotonic() - start
                logger.info("Remote STT: %.1fs, %d samples → '%s'", elapsed, len(audio), text)
                return text
            except Exception as e:
                last_remote_error = e
                logger.warning(
                    "Remote STT failed (attempt %d/%d): %r",
                    attempt + 1,
                    max(self._remote_retries, 0) + 1,
                    e,
                )
                # Tiny backoff for transient network hiccups.
                if attempt < self._remote_retries:
                    await asyncio.sleep(0.15 * (attempt + 1))

        # Local fallback
        if self._use_local_fallback:
            try:
                text = self._transcribe_local(audio)
                elapsed = time.monotonic() - start
                logger.info("Local STT: %.1fs, %d samples → '%s'", elapsed, len(audio), text)
                return text
            except Exception as e:
                if last_remote_error is not None:
                    logger.error("Local STT also failed after remote error %r: %r", last_remote_error, e)
                else:
                    logger.error("Local STT also failed: %r", e)

        return ""

    async def _transcribe_remote(self, audio: np.ndarray) -> str:
        """Send audio to GPU cluster Whisper API."""
        client = await self._get_client()
        wav_bytes = self._audio_to_wav_bytes(audio)

        response = await client.post(
            self._remote_url,
            files={"file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav")},
            data={
                "model": "whisper-1",
                "language": self._language,
                "response_format": "json",
            },
        )
        response.raise_for_status()
        result = response.json()
        return result.get("text", "").strip()

    def _transcribe_local(self, audio: np.ndarray) -> str:
        """Transcribe using local whisper.cpp."""
        if self._local_model is None:
            self._load_local_model()

        if self._local_model is None:
            raise RuntimeError("Local whisper model not available")

        result = self._local_model.transcribe(audio)
        return result.strip()

    def _load_local_model(self):
        """Load local whisper.cpp model."""
        try:
            from whispercpp import Whisper

            self._local_model = Whisper.from_pretrained(
                self._local_model_path,
                n_threads=self._local_threads,
            )
            logger.info("Local whisper model loaded: %s", self._local_model_path)
        except ImportError:
            logger.warning("whisper-cpp-python not installed, local fallback unavailable")
        except Exception as e:
            logger.warning("Failed to load local whisper model: %s", e)

    async def close(self):
        """Clean up HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
