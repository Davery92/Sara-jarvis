"""Local TTS synthesis + playback for the desktop SPEAK command.

Fetches PCM audio from the Kokoro TTS server (same contract used by the
Jetson voice pipeline: POST /v1/audio/speech -> raw int16 PCM) and plays it
through the default (or configured) output device via sounddevice.

Reports playback_state (is_playing True/False) so the HUD orb can show a
"speaking" state and the Jetson's echo suppression (when this desktop is
acting as a routed TTS sink) can stay truthful.
"""
import asyncio
import logging
import re
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+|(?<=\n)\s*")


def _split_sentences(text: str) -> list:
    """Split text into sentences so playback can start before the whole
    response has been synthesized (mirrors the Jetson TTS client)."""
    parts = _SENTENCE_SPLIT.split(text)
    result = []
    buffer = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        buffer += (" " if buffer else "") + part
        if len(buffer) >= 20 or buffer[-1] in ".!?;:":
            result.append(buffer)
            buffer = ""
    if buffer:
        result.append(buffer)
    return result


class PlaybackService:
    """Synthesizes text via Kokoro and plays it on the local output device."""

    def __init__(
        self,
        tts_url: str,
        voice: str,
        speed: float,
        output_device: Optional[str] = None,
        sample_rate: int = 24000,
        on_playback_state: Optional[Callable] = None,
    ):
        self._tts_url = tts_url.rstrip("/")
        self._voice = voice
        self._speed = speed
        self._output_device_match = output_device
        self._sample_rate = sample_rate
        self._on_playback_state = on_playback_state

        self._client = None
        self._cancel_event = asyncio.Event()
        self._playing = False

    def set_voice_config(self, voice: Optional[str] = None, speed: Optional[float] = None) -> None:
        """Live-update voice/speed (Settings > Voice tab), no restart needed."""
        if voice:
            self._voice = voice
        if speed:
            self._speed = speed

    async def _get_client(self):
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _resolve_output_device(self):
        """Find the sounddevice output device index matching the configured
        substring, or None to use the system default."""
        if not self._output_device_match:
            return None
        try:
            import sounddevice as sd
            needle = self._output_device_match.lower()
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_output_channels", 0) > 0 and needle in dev.get("name", "").lower():
                    return idx
        except Exception as e:
            logger.warning(f"Failed to resolve output device '{self._output_device_match}': {e}")
        return None

    async def _synthesize_sentence(self, text: str) -> Optional[np.ndarray]:
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self._tts_url}/v1/audio/speech",
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": self._voice,
                    "speed": self._speed,
                    "response_format": "pcm",
                },
            )
            response.raise_for_status()
            pcm_bytes = response.content
            if not pcm_bytes:
                return None
            return np.frombuffer(pcm_bytes, dtype=np.int16)
        except Exception as e:
            logger.error(f"TTS synthesis failed for '{text[:50]}...': {e}")
            return None

    async def _report_state(self, is_playing: bool):
        self._playing = is_playing
        if self._on_playback_state:
            try:
                result = self._on_playback_state(is_playing)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"playback_state callback failed: {e}")

    async def speak(self, text: str) -> bool:
        """Synthesize and play `text`, sentence by sentence. Returns True if
        any audio actually played (False on total synthesis failure or cancel)."""
        self._cancel_event.clear()
        sentences = _split_sentences(text) or [text]
        played_any = False

        await self._report_state(True)
        try:
            for sentence in sentences:
                if self._cancel_event.is_set():
                    break
                audio = await self._synthesize_sentence(sentence)
                if audio is None or len(audio) == 0:
                    continue
                if self._cancel_event.is_set():
                    break
                await self._play_blocking(audio)
                played_any = True
            return played_any
        finally:
            await self._report_state(False)

    async def _play_blocking(self, audio: np.ndarray):
        """Play a PCM int16 buffer to completion, in a worker thread so the
        event loop stays responsive to a cancel() call."""
        loop = asyncio.get_event_loop()

        def _play():
            import sounddevice as sd
            device = self._resolve_output_device()
            sd.play(audio, samplerate=self._sample_rate, device=device, blocking=False)
            sd.wait()

        play_task = loop.run_in_executor(None, _play)

        # Poll for cancellation while playback runs; sd.stop() halts immediately.
        while not play_task.done():
            if self._cancel_event.is_set():
                try:
                    import sounddevice as sd
                    sd.stop()
                except Exception:
                    pass
                break
            await asyncio.sleep(0.05)

    def cancel(self):
        """Stop any in-progress speech immediately (CANCEL_SPEECH command)."""
        self._cancel_event.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    @property
    def is_playing(self) -> bool:
        return self._playing

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
