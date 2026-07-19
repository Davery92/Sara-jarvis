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
    """Detects "Hey Sara" wake word using OpenWakeWord."""

    def __init__(self, config: dict):
        ww_cfg = config.get("wake_word", {})
        self._model_path = ww_cfg.get("model_path", "models/hey_sara.onnx")
        self._threshold = ww_cfg.get("threshold", 0.90)
        self._ambient_boost = ww_cfg.get("ambient_threshold_boost", 0.15)
        self._refractory_seconds = ww_cfg.get("refractory_seconds", 2.0)
        self._chunk_size = ww_cfg.get("chunk_size", 1280)  # 80ms at 16kHz
        self._consecutive_hits_required = int(ww_cfg.get("consecutive_hits_required", 2))
        self._min_chunk_rms = float(ww_cfg.get("min_chunk_rms", 0.012))
        self._min_rms_hits_required = int(
            ww_cfg.get("min_rms_hits_required", self._consecutive_hits_required)
        )

        allowed = ww_cfg.get("allowed_model_names", ["hey_sara"])
        self._allowed_model_names = {
            self._normalize_model_name(name)
            for name in allowed
            if str(name).strip()
        }
        if not self._allowed_model_names:
            self._allowed_model_names = {"hey_sara"}

        self._model = None
        self._last_trigger_time = 0.0
        self._suppressed = False
        self._ambient_active = False  # Set when music/TV detected
        self._last_detection: dict[str, float | str] = {}

        # Buffer for accumulating audio to chunk_size (int16 PCM for OpenWakeWord)
        self._audio_buffer = np.array([], dtype=np.int16)
        self._hit_streak: dict[str, int] = {}
        self._rms_hit_streak: dict[str, int] = {}

        # Diagnostics for intermittent non-triggers
        self._near_miss_floor = float(ww_cfg.get("near_miss_floor", max(0.60, self._threshold - 0.20)))
        self._near_miss_log_interval = float(ww_cfg.get("near_miss_log_interval_seconds", 2.0))
        self._last_near_miss_log = 0.0

    @staticmethod
    def _normalize_model_name(name: str) -> str:
        """Normalize model labels for exact allowlist matching."""
        return str(name).strip().lower().replace(" ", "_").replace("-", "_")

    def load(self):
        """Load only the configured wake-word model (no bundled fallback)."""
        from openwakeword.model import Model

        model_path = Path(self._model_path)
        if not model_path.exists():
            # Do not fall back to bundled models; user requires hey_sara-only behavior.
            raise FileNotFoundError(
                f"Wake word model required and missing: {model_path}."
            )

        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
        )

        loaded_labels: list[str] = []
        try:
            probe = self._model.predict(np.zeros(self._chunk_size, dtype=np.int16))
            loaded_labels = sorted(str(k) for k in probe.keys())
        except Exception:
            loaded_labels = []

        logger.info(
            "Wake word model loaded: %s (threshold=%.2f, consecutive_hits=%d, min_chunk_rms=%.4f, allowed=%s, loaded=%s)",
            self._model_path,
            self._threshold,
            self._consecutive_hits_required,
            self._min_chunk_rms,
            sorted(self._allowed_model_names),
            loaded_labels,
        )

    def process(self, audio: np.ndarray, ignore_suppression: bool = False) -> bool:
        """Process 16kHz mono audio chunk (float32 -1..1). Returns True if wake word detected.

        `ignore_suppression` is for the B2.5 interim "stop" escape hatch —
        detecting "hey sara" spoken *while Sara is talking* needs to bypass
        the normal suppress()-during-conversation gate (states are mutually
        exclusive, so this never runs concurrently with the gated call).
        """
        if self._model is None:
            return False
        if self._suppressed and not ignore_suppression:
            return False

        # Convert float32 (-1..1) to int16 - OpenWakeWord expects 16-bit PCM
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

            # Check only allowlisted model outputs for detection.
            for model_name, score in prediction.items():
                normalized_name = self._normalize_model_name(model_name)
                if normalized_name not in self._allowed_model_names:
                    continue

                threshold = self._threshold
                if self._ambient_active:
                    threshold += self._ambient_boost

                # Track score streak.
                streak = self._hit_streak.get(normalized_name, 0)
                if score >= threshold:
                    streak += 1
                else:
                    streak = 0
                self._hit_streak[normalized_name] = streak

                # Track voice-energy streak so distant/noisy activations are less likely.
                chunk_f32 = chunk.astype(np.float32) / 32768.0
                chunk_rms = float(np.sqrt(np.mean(chunk_f32 ** 2) + 1e-12))
                rms_streak = self._rms_hit_streak.get(normalized_name, 0)
                if chunk_rms >= self._min_chunk_rms:
                    rms_streak += 1
                else:
                    rms_streak = 0
                self._rms_hit_streak[normalized_name] = rms_streak

                if (
                    score >= self._near_miss_floor
                    and (streak < self._consecutive_hits_required or rms_streak < self._min_rms_hits_required)
                ):
                    now_nm = time.monotonic()
                    if now_nm - self._last_near_miss_log >= self._near_miss_log_interval:
                        self._last_near_miss_log = now_nm
                        logger.info(
                            "Wake near-miss: %s=%.3f (threshold=%.3f, streak=%d/%d, rms=%.4f, rms_streak=%d/%d)",
                            model_name,
                            score,
                            threshold,
                            streak,
                            self._consecutive_hits_required,
                            chunk_rms,
                            rms_streak,
                            self._min_rms_hits_required,
                        )

                if streak < self._consecutive_hits_required:
                    continue
                if rms_streak < self._min_rms_hits_required:
                    continue

                now = time.monotonic()
                if now - self._last_trigger_time >= self._refractory_seconds:
                    self._last_trigger_time = now
                    self._last_detection = {
                        "model": str(model_name),
                        "score": float(score),
                        "threshold": float(threshold),
                        "streak": int(streak),
                        "rms": float(chunk_rms),
                        "monotonic": float(now),
                    }
                    logger.info(
                        "Wake word detected: %s=%.3f (threshold=%.3f, streak=%d, rms=%.4f)",
                        model_name,
                        score,
                        threshold,
                        streak,
                        chunk_rms,
                    )
                    detected = True
                    # Reset streak to avoid immediate retrigger from the same phrase.
                    self._hit_streak[normalized_name] = 0
                    self._rms_hit_streak[normalized_name] = 0

        return detected

    def suppress(self):
        """Suppress wake word detection (e.g., during Sara's speech)."""
        self._suppressed = True

    def unsuppress(self):
        """Re-enable wake word detection."""
        self._suppressed = False
        # Clear buffer to avoid stale audio triggering
        self._audio_buffer = np.array([], dtype=np.int16)
        self._hit_streak.clear()
        self._rms_hit_streak.clear()
        if self._model:
            self._model.reset()

    def set_ambient_active(self, active: bool):
        """Indicate whether ambient audio (music/TV) is present."""
        self._ambient_active = active

    def reset(self):
        """Reset internal state."""
        self._audio_buffer = np.array([], dtype=np.int16)
        self._hit_streak.clear()
        self._rms_hit_streak.clear()
        self._last_detection = {}
        if self._model:
            self._model.reset()

    @property
    def last_detection(self) -> dict:
        """Latest accepted wake detection metadata."""
        return dict(self._last_detection)

    @property
    def is_suppressed(self) -> bool:
        return self._suppressed
