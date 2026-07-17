"""Voice Activity Detection using Silero VAD (PyTorch).

Detects speech boundaries (start/end) from 16kHz mono audio.
Used after wake word to determine when the user has finished speaking.

Note: The ONNX version of Silero VAD is broken on Jetson aarch64
(always returns ~0.0005 regardless of input). PyTorch version works correctly.
"""

import logging
import time
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class VADState(Enum):
    SILENCE = "silence"
    SPEECH = "speech"
    SPEECH_END = "speech_end"


class SileroVAD:
    """Silero VAD for speech boundary detection (PyTorch backend)."""

    def __init__(self, config: dict):
        vad_cfg = config.get("vad", {})
        self._threshold = vad_cfg.get("threshold", 0.5)
        self._min_speech_ms = vad_cfg.get("min_speech_ms", 250)
        self._max_silence_ms = vad_cfg.get("max_silence_ms", 300)
        self._max_speech_seconds = vad_cfg.get("max_speech_seconds", 30)
        self._pre_speech_pad_ms = vad_cfg.get("pre_speech_pad_ms", 300)

        self._sample_rate = config.get("audio", {}).get("target_rate", 16000)

        self._model = None
        self._state = VADState.SILENCE
        self._speech_start_time: float | None = None
        self._last_speech_time: float | None = None
        self._active = False

        # Audio accumulator for collecting speech
        self._speech_audio: list[np.ndarray] = []
        self._pre_speech_buffer: list[np.ndarray] = []
        self._pre_speech_chunks = max(
            1, int(self._pre_speech_pad_ms * self._sample_rate / 1000 / 512)
        )

        # Audio buffer for 512-sample chunks (Silero requires exactly 512 at 16kHz)
        self._chunk_buffer = np.array([], dtype=np.float32)

    def load(self):
        """Load the Silero VAD model via PyTorch."""
        import torch

        self._torch = torch
        self._model, _ = torch.hub.load(
            "snakers4/silero-vad",
            "silero_vad",
            onnx=False,
            trust_repo=True,
        )
        self._model.eval()

        # A second, independent model instance for barge-in confidence
        # probing during SPEAKING (B2.3). Kept separate from self._model so
        # probing doesn't disturb the utterance-capture VAD's own hidden
        # RNN state — they run concurrently in different conversation states
        # but a barge-in probe and a real LISTENING/COOLDOWN session could
        # otherwise corrupt each other's state if they shared one instance.
        self._barge_model, _ = torch.hub.load(
            "snakers4/silero-vad",
            "silero_vad",
            onnx=False,
            trust_repo=True,
        )
        self._barge_model.eval()
        self._barge_chunk_buffer = np.array([], dtype=np.float32)

        logger.info("Silero VAD loaded (PyTorch backend)")

    def reset_barge_state(self):
        """Reset the barge-in prober's hidden state — call at the start of
        each SPEAKING turn so residual state from a prior turn can't bias
        the next one."""
        if self._barge_model is not None:
            self._barge_model.reset_states()
        self._barge_chunk_buffer = np.array([], dtype=np.float32)

    def probe_confidence(self, audio: np.ndarray) -> float | None:
        """Run the barge-in prober on incoming audio during SPEAKING.

        Returns the latest 512-sample chunk's speech probability, or None
        if not enough audio has accumulated yet for a chunk.
        """
        if self._barge_model is None:
            return None

        self._barge_chunk_buffer = np.concatenate([self._barge_chunk_buffer, audio])
        prob = None
        while len(self._barge_chunk_buffer) >= 512:
            chunk = self._barge_chunk_buffer[:512]
            self._barge_chunk_buffer = self._barge_chunk_buffer[512:]
            chunk_tensor = self._torch.from_numpy(chunk)
            prob = self._barge_model(chunk_tensor, self._sample_rate).item()
        return prob

    def _run_inference(self, audio_chunk: np.ndarray) -> float:
        """Run VAD on a single 512-sample chunk. Returns speech probability."""
        if self._model is None:
            return 0.0

        chunk_tensor = self._torch.from_numpy(audio_chunk)
        prob = self._model(chunk_tensor, self._sample_rate).item()
        return prob

    def activate(self):
        """Start VAD processing."""
        self._active = True
        self._state = VADState.SILENCE
        self._speech_start_time = None
        self._last_speech_time = None
        self._speech_audio.clear()
        self._chunk_buffer = np.array([], dtype=np.float32)
        self._reset_hidden()
        logger.debug("VAD activated")

    def deactivate(self):
        """Stop VAD processing."""
        self._active = False
        self._state = VADState.SILENCE
        self._speech_audio.clear()
        self._chunk_buffer = np.array([], dtype=np.float32)
        logger.debug("VAD deactivated")

    def _reset_hidden(self):
        """Reset model hidden states."""
        if self._model is not None:
            self._model.reset_states()

    def process(self, audio: np.ndarray) -> VADState:
        """Process audio chunk and return current VAD state.

        Returns VADState.SPEECH_END when speech segment is complete.
        Call get_speech_audio() after SPEECH_END to retrieve the audio.
        """
        if not self._active or self._model is None:
            return VADState.SILENCE

        # Accumulate audio for 512-sample chunks
        self._chunk_buffer = np.concatenate([self._chunk_buffer, audio])

        now = time.monotonic()

        while len(self._chunk_buffer) >= 512:
            chunk = self._chunk_buffer[:512]
            self._chunk_buffer = self._chunk_buffer[512:]

            prob = self._run_inference(chunk)
            is_speech = prob >= self._threshold

            if self._state == VADState.SILENCE:
                # Maintain pre-speech buffer
                self._pre_speech_buffer.append(chunk.copy())
                if len(self._pre_speech_buffer) > self._pre_speech_chunks:
                    self._pre_speech_buffer.pop(0)

                if is_speech:
                    self._speech_start_time = now
                    self._last_speech_time = now
                    self._state = VADState.SPEECH
                    # Include pre-speech padding
                    self._speech_audio = list(self._pre_speech_buffer)
                    self._speech_audio.append(chunk.copy())
                    self._pre_speech_buffer.clear()
                    logger.info("Speech started (prob=%.3f)", prob)

            elif self._state == VADState.SPEECH:
                self._speech_audio.append(chunk.copy())

                if is_speech:
                    self._last_speech_time = now

                # Check max speech duration
                elapsed = now - (self._speech_start_time or now)
                if elapsed >= self._max_speech_seconds:
                    logger.info("Max speech duration reached (%.1fs)", elapsed)
                    self._state = VADState.SPEECH_END
                    return VADState.SPEECH_END

                # Check end-of-speech silence
                silence_ms = (now - (self._last_speech_time or now)) * 1000
                if not is_speech and silence_ms >= self._max_silence_ms:
                    speech_ms = ((self._last_speech_time or now) - (self._speech_start_time or now)) * 1000
                    if speech_ms >= self._min_speech_ms:
                        logger.info(
                            "Speech ended: duration=%.0fms, silence=%.0fms",
                            speech_ms, silence_ms,
                        )
                        self._state = VADState.SPEECH_END
                        return VADState.SPEECH_END
                    else:
                        # Too short — discard and reset
                        logger.debug("Speech too short (%.0fms), discarding", speech_ms)
                        self._state = VADState.SILENCE
                        self._speech_audio.clear()

        return self._state

    def get_speech_audio(self) -> np.ndarray:
        """Get the captured speech audio after SPEECH_END."""
        if not self._speech_audio:
            return np.array([], dtype=np.float32)
        audio = np.concatenate(self._speech_audio)
        self._speech_audio.clear()
        return audio

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def state(self) -> VADState:
        return self._state
