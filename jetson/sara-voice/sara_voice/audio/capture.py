"""Audio capture from AIRHUG USB speakerphone via sounddevice.

Ring buffer captures continuous audio at native 48kHz stereo,
downmixes to mono and resamples to 16kHz for model consumption.
"""

import logging
import threading
from collections import deque
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from USB mic, maintains a ring buffer of 16kHz mono PCM."""

    def __init__(self, config: dict):
        audio_cfg = config.get("audio", {})
        self._device_name = audio_cfg.get("input_device", "AIRHUG")
        self._fallback_name = audio_cfg.get("fallback_device", "OBSBOT")
        self._native_rate = audio_cfg.get("sample_rate", 48000)
        self._target_rate = audio_cfg.get("target_rate", 16000)
        self._channels = audio_cfg.get("channels", 1)
        self._block_size = audio_cfg.get("block_size", 1024)
        self._buffer_seconds = audio_cfg.get("ring_buffer_seconds", 30)

        self._device_index: int | None = None
        self._stream = None
        self._running = False
        self._lock = threading.Lock()

        # Ring buffer of 16kHz mono float32 chunks
        max_chunks = int(self._target_rate * self._buffer_seconds / self._block_size) + 1
        self._ring_buffer: deque[np.ndarray] = deque(maxlen=max_chunks)

        # Callbacks for real-time audio consumers
        self._listeners: list[Callable[[np.ndarray], None]] = []

        # Resample ratio
        self._resample_ratio = self._target_rate / self._native_rate

    def _find_device(self) -> int:
        """Find the audio input device by substring match."""
        import sounddevice as sd

        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                if self._device_name.lower() in dev["name"].lower():
                    logger.info("Found audio device: %s (index %d)", dev["name"], i)
                    return i

        # Fallback device
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                if self._fallback_name.lower() in dev["name"].lower():
                    logger.warning("Primary device not found, using fallback: %s", dev["name"])
                    return i

        # Last resort: default input
        default = sd.default.device[0]
        if default is not None and default >= 0:
            logger.warning("No named device found, using system default input (index %d)", default)
            return int(default)

        raise RuntimeError("No audio input device found")

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        """Resample from native rate to target rate using scipy."""
        from scipy.signal import resample_poly
        from math import gcd

        up = self._target_rate
        down = self._native_rate
        g = gcd(up, down)
        return resample_poly(audio, up // g, down // g).astype(np.float32)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """sounddevice callback — runs in audio thread."""
        if status:
            logger.debug("Audio status: %s", status)

        # Convert to float32 mono
        audio = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        audio = audio.astype(np.float32).flatten()

        # Resample 48kHz → 16kHz
        if self._native_rate != self._target_rate:
            audio = self._resample(audio)

        with self._lock:
            self._ring_buffer.append(audio)

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(audio)
            except Exception:
                logger.exception("Audio listener error")

    def add_listener(self, callback: Callable[[np.ndarray], None]):
        """Register a callback for real-time 16kHz mono audio chunks."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[np.ndarray], None]):
        """Unregister a callback."""
        self._listeners = [cb for cb in self._listeners if cb is not callback]

    def get_recent_audio(self, seconds: float) -> np.ndarray:
        """Get the last N seconds of audio from the ring buffer."""
        chunks_needed = int(self._target_rate * seconds / self._block_size) + 1
        with self._lock:
            chunks = list(self._ring_buffer)[-chunks_needed:]
        if not chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks)

    def start(self):
        """Start audio capture."""
        import sounddevice as sd

        if self._running:
            return

        self._device_index = self._find_device()

        # Query actual device channels
        dev_info = sd.query_devices(self._device_index)
        input_channels = min(dev_info["max_input_channels"], 2)

        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=self._native_rate,
            channels=input_channels,
            blocksize=self._block_size,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()
        self._running = True
        logger.info(
            "Audio capture started: device=%d, rate=%d→%d, channels=%d→1",
            self._device_index, self._native_rate, self._target_rate, input_channels,
        )

    def stop(self):
        """Stop audio capture."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False
        logger.info("Audio capture stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def sample_rate(self) -> int:
        return self._target_rate
