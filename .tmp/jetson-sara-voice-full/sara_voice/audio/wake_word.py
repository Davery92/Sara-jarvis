"""Wake word detection using OpenWakeWord with CPU ONNX Runtime.

Runs continuously on CPU (ONNX Runtime CUDA is broken on Jetson).
Detects "Hey Sara" from 16kHz mono audio chunks.
"""

import logging
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Detects 'Hey Sara' wake word using OpenWakeWord."""

    def __init__(self, config: dict):
        ww_cfg = config.get("wake_word", {})
        self._model_path = ww_cfg.get("model_path", "models/hey_sara.onnx")
        self._threshold = ww_cfg.get("threshold", 0.5)
        self._ambient_boost = ww_cfg.get("ambient_threshold_boost", 0.15)
        self._refractory_seconds = ww_cfg.get("refractory_seconds", 2.0)
        self._chunk_size = ww_cfg.get("chunk_size", 1280)  # 80ms at 16kHz

        self._model = None
        self._last_trigger_time = 0.0
        self._suppressed = False
        self._ambient_active = False  # Set when music/TV detected

        # Buffer for accumulating audio to chunk_size (int16 PCM for OpenWakeWord)
        self._audio_buffer = np.array([], dtype=np.int16)

    def load(self):
        """Load the OpenWakeWord model."""
        from openwakeword.model import Model

        model_path = Path(self._model_path)
        if not model_path.exists():
            logger.warning("Wake word model not found at %s — using bundled models", model_path)
            self._model = Model(inference_framework="onnx")
        else:
            self._model = Model(
                wakeword_models=[str(model_path)],
                inference_framework="onnx",
            )
        logger.info("Wake word model loaded: %s", self._model_path)

    def process(self, audio: np.ndarray) -> bool:
        """Process 16kHz mono audio chunk (float32 -1..1). Returns True if wake word detected."""
        if self._model is None or self._suppressed:
            return False

        # Convert float32 (-1..1) to int16 — OpenWakeWord expects 16-bit PCM
        if audio.dtype == np.float32:
            audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)

        # Accumulate audio until we have enough for a chunk
        self._audio_buffer = np.concatenate([self._audio_buffer, audio])

        detected = False
        while len(self._audio_buffer) >= self._chunk_size:
            chunk = self._audio_buffer[:self._chunk_size]
            self._audio_buffer = self._audio_buffer[self._chunk_size:]

            # Run prediction
            prediction = self._model.predict(chunk)

            # Check all model outputs for detection
            for model_name, score in prediction.items():
                threshold = self._threshold
                if self._ambient_active:
                    threshold += self._ambient_boost

                if score >= threshold:
                    now = time.monotonic()
                    if now - self._last_trigger_time >= self._refractory_seconds:
                        self._last_trigger_time = now
                        logger.info(
                            "Wake word detected: %s=%.3f (threshold=%.3f)",
                            model_name, score, threshold,
                        )
                        detected = True

        return detected

    def suppress(self):
        """Suppress wake word detection (e.g., during Sara's speech)."""
        self._suppressed = True

    def unsuppress(self):
        """Re-enable wake word detection."""
        self._suppressed = False
        # Clear buffer to avoid stale audio triggering
        self._audio_buffer = np.array([], dtype=np.int16)
        if self._model:
            self._model.reset()

    def set_ambient_active(self, active: bool):
        """Indicate whether ambient audio (music/TV) is present."""
        self._ambient_active = active

    def reset(self):
        """Reset internal state."""
        self._audio_buffer = np.array([], dtype=np.int16)
        if self._model:
            self._model.reset()

    @property
    def is_suppressed(self) -> bool:
        return self._suppressed
