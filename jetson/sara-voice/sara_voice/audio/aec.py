"""Software Acoustic Echo Cancellation (AEC).

Since the AIRHUG has no hardware AEC, we implement software-based
echo cancellation using a reference signal from the desktop bridge.
The desktop bridge reports when Sara is speaking and sends echo state.

This module uses a simple approach:
1. Track echo state from desktop bridge (is_playing)
2. During playback, suppress the mic input
3. After playback ends, apply tail suppression for residual echo
4. Optionally use spectral subtraction if reference signal available
"""

import logging
import time

import numpy as np

logger = logging.getLogger(__name__)


class EchoCanceller:
    """Software echo cancellation using reference signal tracking."""

    def __init__(self, config: dict):
        echo_cfg = config.get("echo", {})
        self._tail_ms = echo_cfg.get("tail_suppression_ms", 500)
        self._ref_delay_ms = echo_cfg.get("reference_delay_ms", 50)

        self._sample_rate = config.get("audio", {}).get("target_rate", 16000)

        # State
        self._is_playing = False
        self._playback_end_time: float | None = None
        self._suppression_active = False

        # Spectral subtraction state
        self._reference_spectrum: np.ndarray | None = None
        self._fft_size = 512
        self._subtraction_gain = 0.8  # How much of reference to subtract

    def update_playback_state(self, is_playing: bool):
        """Called by desktop bridge when playback state changes."""
        was_playing = self._is_playing
        self._is_playing = is_playing

        if was_playing and not is_playing:
            # Playback just ended — start tail suppression
            self._playback_end_time = time.monotonic()
            self._suppression_active = True
            logger.debug("Playback ended, tail suppression started")
        elif not was_playing and is_playing:
            # Playback started
            self._playback_end_time = None
            self._suppression_active = True
            logger.debug("Playback started, suppression active")

    def update_reference_audio(self, reference: np.ndarray):
        """Update reference spectrum from TTS audio (for spectral subtraction)."""
        if len(reference) >= self._fft_size:
            # Compute average spectrum of reference
            n_frames = len(reference) // self._fft_size
            spectra = []
            for i in range(n_frames):
                frame = reference[i * self._fft_size:(i + 1) * self._fft_size]
                spectrum = np.abs(np.fft.rfft(frame * np.hanning(self._fft_size)))
                spectra.append(spectrum)
            if spectra:
                self._reference_spectrum = np.mean(spectra, axis=0)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply echo cancellation to mic audio."""
        now = time.monotonic()

        # During active playback: hard suppress
        if self._is_playing:
            return audio * 0.01  # Near-zero but not exactly zero

        # Tail suppression after playback ends
        if self._playback_end_time is not None:
            elapsed_ms = (now - self._playback_end_time) * 1000
            if elapsed_ms < self._tail_ms:
                # Fade in from suppression
                fade = elapsed_ms / self._tail_ms
                fade = max(0.0, min(1.0, fade))
                return audio * fade
            else:
                # Tail suppression complete
                self._playback_end_time = None
                self._suppression_active = False
                self._reference_spectrum = None

        # If we have a reference spectrum, do spectral subtraction
        if self._reference_spectrum is not None and len(audio) >= self._fft_size:
            return self._spectral_subtract(audio)

        return audio

    def _spectral_subtract(self, audio: np.ndarray) -> np.ndarray:
        """Remove estimated echo using spectral subtraction."""
        result = np.zeros_like(audio)
        window = np.hanning(self._fft_size)

        n_frames = len(audio) // self._fft_size
        for i in range(n_frames):
            start = i * self._fft_size
            end = start + self._fft_size
            frame = audio[start:end] * window

            spectrum = np.fft.rfft(frame)
            magnitude = np.abs(spectrum)
            phase = np.angle(spectrum)

            # Subtract reference spectrum
            cleaned_mag = magnitude - self._subtraction_gain * self._reference_spectrum
            cleaned_mag = np.maximum(cleaned_mag, magnitude * 0.1)  # Floor

            cleaned = cleaned_mag * np.exp(1j * phase)
            result[start:end] += np.fft.irfft(cleaned)[:self._fft_size]

        # Handle remaining samples
        remaining = len(audio) - n_frames * self._fft_size
        if remaining > 0:
            result[-remaining:] = audio[-remaining:]

        return result

    @property
    def is_suppressing(self) -> bool:
        return self._suppression_active or self._is_playing
