"""Adaptive spectral noise gate for ambient music/TV environments.

Estimates ambient noise floor using a rolling window, applies
a soft gate that lets speech through while suppressing background.
"""

import logging
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)


class NoiseGate:
    """Adaptive noise gate that tracks ambient levels and gates below them."""

    def __init__(self, config: dict):
        ng_cfg = config.get("noise_gate", {})
        self._enabled = ng_cfg.get("enabled", True)
        self._floor_db = ng_cfg.get("floor_db", -50)
        self._attack_ms = ng_cfg.get("attack_ms", 5)
        self._release_ms = ng_cfg.get("release_ms", 100)
        self._adaptive = ng_cfg.get("adaptive", True)
        self._ambient_window = ng_cfg.get("ambient_window_seconds", 10)

        sample_rate = config.get("audio", {}).get("target_rate", 16000)
        self._sample_rate = sample_rate

        # Adaptive ambient tracking — store RMS values
        rms_per_second = sample_rate // config.get("audio", {}).get("block_size", 1024)
        window_size = max(1, rms_per_second * self._ambient_window)
        self._rms_history: deque[float] = deque(maxlen=int(window_size))

        # Gate state for smooth open/close
        self._gate_level = 0.0  # 0=closed, 1=open
        self._attack_coeff = self._time_constant(self._attack_ms, sample_rate)
        self._release_coeff = self._time_constant(self._release_ms, sample_rate)

        # Current ambient estimate
        self._ambient_rms = 10 ** (self._floor_db / 20)

    @staticmethod
    def _time_constant(ms: float, sample_rate: int) -> float:
        """Convert milliseconds to exponential smoothing coefficient."""
        if ms <= 0:
            return 1.0
        samples = ms * sample_rate / 1000
        return 1.0 - np.exp(-1.0 / max(samples, 1))

    def _update_ambient(self, rms: float):
        """Update ambient noise floor estimate."""
        self._rms_history.append(rms)
        if len(self._rms_history) >= 10:
            # Use 25th percentile as ambient floor estimate
            sorted_rms = sorted(self._rms_history)
            idx = len(sorted_rms) // 4
            self._ambient_rms = sorted_rms[idx]

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply noise gate to audio chunk. Returns gated audio.

        Ambient-level measurement runs regardless of `_enabled` — B2.4's
        ambient-aware wake threshold needs `ambient_db` to stay live even
        when actual gating is turned off, so the estimate can't go stale.
        """
        rms = float(np.sqrt(np.mean(audio ** 2) + 1e-10))

        if self._adaptive:
            self._update_ambient(rms)

        if not self._enabled:
            return audio

        # Gate threshold: slightly above ambient floor
        threshold = self._ambient_rms * 2.0

        if rms > threshold:
            # Open gate (attack)
            self._gate_level += self._attack_coeff * (1.0 - self._gate_level)
        else:
            # Close gate (release)
            self._gate_level -= self._release_coeff * self._gate_level

        self._gate_level = max(0.0, min(1.0, self._gate_level))

        return audio * self._gate_level

    @property
    def ambient_db(self) -> float:
        """Current ambient noise floor in dBFS."""
        if self._ambient_rms <= 0:
            return -100.0
        return 20 * np.log10(max(self._ambient_rms, 1e-10))

    @property
    def is_gate_open(self) -> bool:
        return self._gate_level > 0.5

    @property
    def ambient_rms(self) -> float:
        return self._ambient_rms
