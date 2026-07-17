"""Jetson bridge client — the reconciled voice_bridge.py (Desktop Jarvis
Overhaul D4/A6).

Connects to the Jetson's desktop_bridge WebSocket server (ws://<host>:8765)
when reachable (i.e. on the home network), plays the PCM audio it streams
for TTS playback, and reports echo/playback state back so the Jetson's
barge-in and cooldown logic stay accurate. Auto-reconnects with backoff so
it just quietly stops trying (and quietly resumes) as the home network
comes and goes.

Wire contract (matches jetson/sara-voice/sara_voice/clients/desktop_bridge.py):
  Jetson -> desktop: bare binary int16 PCM frames (playback audio); JSON
    events {"event": "wake_word"|"listening"|"idle"|"transcript"|
    "speaking_start"|"stop_playback", ...}.
  Desktop -> Jetson: JSON {"event": "echo_state", "is_playing": bool},
    {"event": "playback_complete"}, {"event": "stop_confirmed"},
    {"type": "set_listening", "enabled": bool}, {"type": "get_status"}.
"""
import asyncio
import json
import logging
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


class JetsonClient:
    def __init__(
        self,
        host: str,
        port: int = 8765,
        sample_rate: int = 24000,
        on_voice_state: Optional[Callable] = None,
        on_transcript: Optional[Callable] = None,
    ):
        self._host = host
        self._port = port
        self._sample_rate = sample_rate
        self._on_voice_state = on_voice_state
        self._on_transcript = on_transcript

        self._ws = None
        self._running = False
        self._reconnect_delay = 2.0
        self._max_reconnect_delay = 30.0
        self._is_playing = False
        self._stop_requested = False

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def run(self):
        """Connect-and-serve loop with backoff. Runs until stop() is called."""
        import websockets

        self._running = True
        while self._running:
            try:
                url = f"ws://{self._host}:{self._port}"
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_delay = 2.0
                    logger.info(f"Connected to Jetson bridge at {url}")
                    await self._listen(ws)
            except Exception as e:
                logger.debug(f"Jetson bridge unreachable ({e}); retrying in {self._reconnect_delay:.0f}s")
            finally:
                self._ws = None

            if not self._running:
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 1.5, self._max_reconnect_delay)

    async def stop(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _listen(self, ws):
        async for message in ws:
            if isinstance(message, (bytes, bytearray)):
                await self._handle_audio(bytes(message))
            else:
                await self._handle_json(message)

    async def _handle_json(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        event = data.get("event") or data.get("type")

        if event == "stop_playback":
            self._stop_requested = True
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            await self._send({"event": "stop_confirmed"})
            self._is_playing = False
            if self._on_voice_state:
                await self._on_voice_state("idle")
            return

        if event in ("wake_word", "listening", "idle", "speaking_start"):
            state_map = {
                "wake_word": "listening",
                "listening": "listening",
                "idle": "idle",
                "speaking_start": "speaking",
            }
            if self._on_voice_state:
                await self._on_voice_state(state_map[event])
            return

        if event == "transcript" and self._on_transcript:
            await self._on_transcript(data.get("user"), data.get("sara"))
            return

    async def _handle_audio(self, pcm_bytes: bytes):
        """Play a bare int16 PCM chunk streamed from the Jetson's TTS."""
        if not pcm_bytes:
            return

        if not self._is_playing:
            self._is_playing = True
            self._stop_requested = False
            await self._send({"event": "echo_state", "is_playing": True})
            if self._on_voice_state:
                await self._on_voice_state("speaking")

        try:
            import sounddevice as sd
            audio = np.frombuffer(pcm_bytes, dtype=np.int16)
            sd.play(audio, samplerate=self._sample_rate, blocking=False)
            # Give the OS a moment to start playback before the next chunk;
            # actual completion is reported below via a short settle window
            # since the Jetson streams chunk-by-chunk rather than one blob.
            await asyncio.sleep(len(audio) / self._sample_rate * 0.9)
        except Exception as e:
            logger.error(f"Jetson audio playback failed: {e}")

        if not self._stop_requested:
            asyncio.get_event_loop().call_later(
                0.6, lambda: asyncio.ensure_future(self._maybe_report_done())
            )

    async def _maybe_report_done(self):
        """Called ~600ms after the last chunk; if nothing new arrived, treat
        playback as complete (the Jetson doesn't send an explicit end-of-
        stream marker — chunk-silence is the signal, mirroring the sentence-
        pause cadence the TTS client already streams with)."""
        if self._is_playing and not self._stop_requested:
            self._is_playing = False
            await self._send({"event": "playback_complete"})
            await self._send({"event": "echo_state", "is_playing": False})
            if self._on_voice_state:
                await self._on_voice_state("idle")

    async def send_listening(self, enabled: bool):
        await self._send({"type": "set_listening", "enabled": enabled})

    async def stop_playback(self):
        """Halt local playback of Jetson-streamed audio (CANCEL_SPEECH)."""
        self._stop_requested = True
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._is_playing = False
        await self._send({"event": "stop_confirmed"})

    async def _send(self, payload: dict):
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.debug(f"Failed to send to Jetson bridge: {e}")
