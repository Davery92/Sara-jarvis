"""Voice note recorder — mic capture, level meter, transcribe, create note.

Desktop Jarvis Overhaul A4: "record a note" away from the Jetson. Opens the
default input device, streams a live level meter to the renderer, stops on
a second toggle or on a silence timeout, then transcribes and files the
result as a note titled "Voice note — <ET timestamp>".
"""
import asyncio
import logging
import time
import wave
from datetime import datetime
from io import BytesIO
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SAMPLE_RATE = 16000
SILENCE_RMS_THRESHOLD = 0.01
SILENCE_TIMEOUT_SECONDS = 3.0
MAX_RECORDING_SECONDS = 120.0


class VoiceRecorder:
    """Records from the default mic until stopped or silence times out."""

    def __init__(
        self,
        api_url: str,
        auth_token_getter: Callable[[], str],
        on_level: Optional[Callable] = None,
        on_done: Optional[Callable] = None,
    ):
        self._api_url = api_url.rstrip("/")
        self._auth_token_getter = auth_token_getter
        self._on_level = on_level
        self._on_done = on_done

        self._recording = False
        self._frames: list = []
        self._stream = None
        self._last_voice_at = 0.0
        self._started_at = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def toggle(self):
        """Start recording if idle, stop-and-process if already recording."""
        if self._recording:
            asyncio.ensure_future(self._stop())
        else:
            self._start()

    def _start(self):
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not installed; cannot record voice notes")
            return

        self._frames = []
        self._recording = True
        self._started_at = time.time()
        self._last_voice_at = self._started_at
        self._loop = asyncio.get_event_loop()

        def _callback(indata, frame_count, time_info, status):
            if status:
                logger.debug(f"Recorder stream status: {status}")
            mono = indata[:, 0].copy()
            self._frames.append(mono)
            rms = float(np.sqrt(np.mean(mono ** 2) + 1e-10))
            now = time.time()
            if rms > SILENCE_RMS_THRESHOLD:
                self._last_voice_at = now

            if self._loop and self._on_level:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._safe_on_level(min(1.0, rms * 8)))
                )

            if now - self._last_voice_at > SILENCE_TIMEOUT_SECONDS or now - self._started_at > MAX_RECORDING_SECONDS:
                if self._loop:
                    self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._stop()))

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=_callback
        )
        self._stream.start()
        logger.info("Voice note recording started")

    async def _safe_on_level(self, level: float):
        try:
            result = self._on_level(level)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"on_level callback failed: {e}")

    async def _stop(self):
        if not self._recording:
            return
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Failed to stop recorder stream: {e}")
            self._stream = None

        logger.info("Voice note recording stopped, processing...")
        try:
            result = await self._process()
            if self._on_done:
                await self._on_done(result)
        except Exception as e:
            logger.error(f"Voice note processing failed: {e}")
            if self._on_done:
                await self._on_done({"success": False, "error": str(e)})

    def _frames_to_wav_bytes(self) -> bytes:
        audio = np.concatenate(self._frames) if self._frames else np.zeros(0, dtype=np.float32)
        pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        buf = BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm16.tobytes())
        return buf.getvalue()

    async def _process(self) -> dict:
        import httpx

        wav_bytes = self._frames_to_wav_bytes()
        duration = len(wav_bytes) / (SAMPLE_RATE * 2)
        if duration < 0.5:
            return {"success": False, "error": "recording too short"}

        token = self._auth_token_getter()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            transcribe_resp = await client.post(
                f"{self._api_url}/api/pi-dashboard/voice/transcribe",
                headers=headers,
                files={"audio": ("voice_note.wav", wav_bytes, "audio/wav")},
            )
            transcribe_resp.raise_for_status()
            transcript = (transcribe_resp.json().get("transcription") or "").strip()

            if not transcript:
                return {"success": False, "error": "empty transcription"}

            # Avoid %-d/%-I (glibc-only, not portable to Windows' strftime).
            now = datetime.now(ET)
            hour12 = now.hour % 12 or 12
            timestamp = f"{now.strftime('%b')} {now.day}, {now.year} {hour12}:{now.strftime('%M %p')}"
            title = f"Voice note — {timestamp}"

            note_resp = await client.post(
                f"{self._api_url}/notes",
                headers=headers,
                json={"title": title, "content": transcript},
            )
            note_resp.raise_for_status()
            note = note_resp.json()

            return {"success": True, "note": note, "transcript": transcript}
