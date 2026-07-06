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

    async def synthesize_streaming(self, text_chunks):
        """Synthesize audio as text streams in from the LLM, instead of
        waiting for the full response (B4 latency fix — begin speaking
        after the first sentence, not the full response).

        `text_chunks` is an async iterator of text deltas (e.g. from
        BackendClient.voice_chat). Yields (audio: np.ndarray, sentence:
        str) pairs as each complete sentence becomes available; callers
        should join the yielded `sentence` values to reconstruct the full
        response text (needed for raw-buffer logging, bridge transcript
        events, etc.) since this method doesn't buffer the whole thing.
        """
        buffer = ""
        async for delta in text_chunks:
            buffer += delta
            while True:
                sentence, buffer = self._pop_complete_sentence(buffer)
                if sentence is None:
                    break
                audio = await self._synthesize_sentence(sentence)
                if audio is not None and len(audio) > 0:
                    yield audio, sentence
                else:
                    yield None, sentence

        # Flush whatever's left when the stream ends (may not end in
        # punctuation — that's fine, it's the last fragment either way).
        remainder = buffer.strip()
        if remainder:
            audio = await self._synthesize_sentence(remainder)
            yield (audio if audio is not None and len(audio) > 0 else None), remainder

    def _pop_complete_sentence(self, buffer: str) -> tuple[str | None, str]:
        """Pull one complete sentence off the front of `buffer`, if any.

        Returns (sentence_or_None, remaining_buffer). A "complete sentence"
        mirrors _split_sentences' flush rule: ends in terminal punctuation
        and is long enough to be worth synthesizing on its own, so we don't
        fire off a TTS call for every three-word fragment.
        """
        stripped = buffer.lstrip()
        for i, ch in enumerate(stripped):
            if ch in ".!?" and i >= 15:
                # Require the punctuation to actually end a sentence (not
                # "Dr." or "3.5") — a following space/newline or end-of-buffer.
                if i + 1 == len(stripped) or stripped[i + 1] in " \n\t":
                    return stripped[: i + 1].strip(), stripped[i + 1:]
        return None, buffer

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
