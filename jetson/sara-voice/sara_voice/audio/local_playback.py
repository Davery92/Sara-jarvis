"""Local (AIRHUG) TTS playback — Desktop Jarvis Overhaul D3/B2.

Plays synthesized speech out the Jetson's own AIRHUG speaker instead of
routing it to the desktop. Colocating playback and mic on the same device
tightens the timing of the existing software echo suppression (aec.py) —
the desktop-relay path has network round-trip jitter between "playback
started" and the Jetson's own echo-state gating picking that up; local
playback removes that gap entirely.

Note: aec.py's own docstring says the AIRHUG has no hardware AEC — the
gain here is a tighter reference signal for our software gating, not
literal hardware echo cancellation. The desktop sink remains available
for "play this on my PC" and as an automatic fallback.
"""
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class LocalPlayback:
    """Blocking-per-chunk playback through the Jetson's local output device."""

    def __init__(self, config: dict):
        audio_cfg = config.get("audio", {})
        self._output_device_match = audio_cfg.get("output_device", "AIRHUG")
        self._sample_rate = config.get("desktop_bridge", {}).get("audio_format", {}).get("sample_rate", 24000)
        self._stop_requested = False

    def _resolve_device(self) -> Optional[int]:
        try:
            import sounddevice as sd
            needle = (self._output_device_match or "").lower()
            if not needle:
                return None
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_output_channels", 0) > 0 and needle in dev.get("name", "").lower():
                    return idx
        except Exception as e:
            logger.warning("Failed to resolve local output device '%s': %s", self._output_device_match, e)
        return None

    async def play_and_wait(self, pcm: np.ndarray) -> None:
        """Play one PCM chunk to completion. Returns immediately if stop()
        was called since the last chunk (lets a barge-in cut playback
        between chunks without an extra round trip)."""
        if self._stop_requested or len(pcm) == 0:
            return

        import asyncio
        loop = asyncio.get_event_loop()

        def _play():
            import sounddevice as sd
            device = self._resolve_device()
            sd.play(pcm, samplerate=self._sample_rate, device=device, blocking=True)

        await loop.run_in_executor(None, _play)

    def stop(self) -> None:
        self._stop_requested = True
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def rearm(self) -> None:
        """Call at the start of each new response — clears a stop() from a
        previous turn so this turn can actually play."""
        self._stop_requested = False

    async def play_chime(self, frequency: float = 880.0, duration_ms: int = 120) -> None:
        """Short synthesized wake-confirmation tone (B4) — no audio asset to
        bundle, just a clean sine blip with a fast fade to avoid a click."""
        try:
            sample_rate = 24000
            t = np.linspace(0, duration_ms / 1000, int(sample_rate * duration_ms / 1000), endpoint=False)
            tone = np.sin(2 * np.pi * frequency * t)
            fade = min(len(tone) // 8, 200)
            if fade > 0:
                tone[:fade] *= np.linspace(0, 1, fade)
                tone[-fade:] *= np.linspace(1, 0, fade)
            pcm = (tone * 0.3 * 32767).astype(np.int16)

            import asyncio
            loop = asyncio.get_event_loop()

            def _play():
                import sounddevice as sd
                device = self._resolve_device()
                sd.play(pcm, samplerate=sample_rate, device=device, blocking=True)

            await loop.run_in_executor(None, _play)
        except Exception as e:
            logger.debug("Wake chime playback failed: %s", e)
