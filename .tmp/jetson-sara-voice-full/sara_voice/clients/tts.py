"""Kokoro TTS client for sentence-by-sentence streaming.

Converts text to speech using Kokoro TTS server, streaming
PCM audio chunks for low-latency playback on the desktop.
"""

import asyncio
import io
import logging
import re

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class TTSClient:
    """Kokoro TTS client with sentence-level streaming."""

    def __init__(self, config: dict):
        tts_cfg = config.get("tts", {})
        self._url = tts_cfg.get("url", "http://10.185.1.9:8880")
        self._voice = tts_cfg.get("voice", "af_heart")
        self._speed = tts_cfg.get("speed", 1.0)
        self._sentence_pause_ms = tts_cfg.get("sentence_pause_ms", 150)
        self._format = tts_cfg.get("format", "pcm")

        bridge_cfg = config.get("desktop_bridge", {}).get("audio_format", {})
        self._output_rate = bridge_cfg.get("sample_rate", 24000)

        self._client: httpx.AsyncClient | None = None

        # Sentence splitting pattern
        self._sentence_pattern = re.compile(
            r'(?<=[.!?;:])\s+|(?<=\n)\s*'
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences for streaming TTS."""
        sentences = self._sentence_pattern.split(text)
        # Filter empty and merge very short fragments
        result = []
        buffer = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            buffer += (" " if buffer else "") + s
            # Flush if sentence is long enough or ends with punctuation
            if len(buffer) >= 20 or buffer[-1] in ".!?;:":
                result.append(buffer)
                buffer = ""
        if buffer:
            result.append(buffer)
        return result

    async def synthesize(self, text: str):
        """Synthesize text to speech, yielding PCM audio chunks per sentence.

        Yields numpy arrays of int16 PCM audio at the configured sample rate.
        """
        sentences = self._split_sentences(text)

        for i, sentence in enumerate(sentences):
            try:
                audio = await self._synthesize_sentence(sentence)
                if audio is not None and len(audio) > 0:
                    yield audio

                    # Pause between sentences (silence)
                    if i < len(sentences) - 1 and self._sentence_pause_ms > 0:
                        silence_samples = int(self._output_rate * self._sentence_pause_ms / 1000)
                        yield np.zeros(silence_samples, dtype=np.int16)
            except Exception as e:
                logger.error("TTS error for sentence '%s...': %s", sentence[:50], e)
                continue

    async def _synthesize_sentence(self, text: str) -> np.ndarray | None:
        """Synthesize a single sentence to PCM audio."""
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self._url}/v1/audio/speech",
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": self._voice,
                    "speed": self._speed,
                    "response_format": "pcm",
                },
            )
            response.raise_for_status()

            # Response is raw PCM bytes (int16, mono, at server's sample rate)
            pcm_bytes = response.content
            if not pcm_bytes:
                return None

            audio = np.frombuffer(pcm_bytes, dtype=np.int16)
            return audio

        except httpx.HTTPStatusError as e:
            logger.error("TTS HTTP error: %s", e)
            return None
        except Exception as e:
            logger.error("TTS request failed: %s", e)
            return None

    async def check_health(self) -> bool:
        """Check if TTS server is reachable."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self._url}/v1/models", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
