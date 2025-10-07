"""
Voice Activity Detection using Silero VAD
Detects speech start/stop for clean recording windows
"""
import torch
import numpy as np
import logging
from typing import Optional, Callable
from collections import deque

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Silero VAD-based voice activity detector"""

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 200,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30
    ):
        """
        Initialize VAD

        Args:
            sample_rate: Audio sample rate (must be 16kHz for Silero)
            threshold: Speech probability threshold 0-1 (default 0.5)
            min_speech_duration_ms: Minimum speech duration to trigger (default 200ms)
            min_silence_duration_ms: Silence duration to end speech (default 500ms)
            speech_pad_ms: Padding before/after speech (default 30ms)
        """
        if sample_rate != 16000:
            raise ValueError("Silero VAD requires 16kHz sample rate")

        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms

        # Load Silero VAD model
        try:
            logger.info("Loading Silero VAD model...")
            torch.set_num_threads(1)  # Optimize for real-time
            self.model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False  # Use PyTorch model
            )
            self.get_speech_timestamps = utils[0]
            logger.info("✅ Silero VAD model loaded")
        except Exception as e:
            logger.error(f"Failed to load Silero VAD: {e}")
            raise

        # State tracking
        self.is_speech = False
        self.speech_start_time = 0
        self.silence_start_time = 0
        self.current_window = []

        # Convert durations to samples
        self.min_speech_samples = int(sample_rate * min_speech_duration_ms / 1000)
        self.min_silence_samples = int(sample_rate * min_silence_duration_ms / 1000)
        self.speech_pad_samples = int(sample_rate * speech_pad_ms / 1000)

    def process_chunk(self, audio_chunk: np.ndarray) -> dict:
        """
        Process audio chunk and detect speech activity

        Args:
            audio_chunk: Audio samples (int16 or float32, 16kHz)

        Returns:
            dict with:
                - is_speech: bool (currently speaking)
                - speech_started: bool (speech just started)
                - speech_ended: bool (speech just ended)
                - probability: float (speech probability 0-1)
        """
        # Convert to float32 if needed
        if audio_chunk.dtype == np.int16:
            audio_float = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio_float = audio_chunk.astype(np.float32)

        # Convert to torch tensor
        audio_tensor = torch.from_numpy(audio_float)

        # Get speech probability
        with torch.no_grad():
            speech_prob = self.model(audio_tensor, self.sample_rate).item()

        # Track state changes
        speech_started = False
        speech_ended = False
        prev_is_speech = self.is_speech

        # Determine if currently speech
        if speech_prob > self.threshold:
            # Speech detected
            if not self.is_speech:
                # Check if sustained long enough
                if self.speech_start_time == 0:
                    self.speech_start_time = len(self.current_window)
                elif len(self.current_window) - self.speech_start_time >= self.min_speech_samples:
                    # Speech sustained long enough
                    self.is_speech = True
                    speech_started = True
                    self.silence_start_time = 0
                    logger.debug(f"🎤 Speech started (prob: {speech_prob:.2f})")
            else:
                # Still speaking
                self.silence_start_time = 0
        else:
            # Silence detected
            if self.is_speech:
                # Check if silence sustained long enough
                if self.silence_start_time == 0:
                    self.silence_start_time = len(self.current_window)
                elif len(self.current_window) - self.silence_start_time >= self.min_silence_samples:
                    # Silence sustained long enough
                    self.is_speech = False
                    speech_ended = True
                    self.speech_start_time = 0
                    logger.debug(f"🔇 Speech ended (prob: {speech_prob:.2f})")
            else:
                # Still silent
                self.speech_start_time = 0

        # Add to window (for state tracking)
        self.current_window.append(audio_chunk)
        # Keep window manageable (1 second)
        if len(self.current_window) > self.sample_rate:
            self.current_window.pop(0)

        return {
            'is_speech': self.is_speech,
            'speech_started': speech_started,
            'speech_ended': speech_ended,
            'probability': speech_prob
        }

    def reset(self):
        """Reset VAD state"""
        self.is_speech = False
        self.speech_start_time = 0
        self.silence_start_time = 0
        self.current_window = []
        logger.debug("VAD reset")

    def set_threshold(self, threshold: float):
        """Dynamically adjust speech threshold"""
        if not 0 <= threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        self.threshold = threshold
        logger.info(f"VAD threshold updated to {threshold}")


class RecordingWindow:
    """
    Manages recording windows with VAD
    Captures audio from speech start to speech end
    """

    def __init__(
        self,
        vad: VoiceActivityDetector,
        on_recording_start: Optional[Callable] = None,
        on_recording_stop: Optional[Callable[[np.ndarray], None]] = None
    ):
        """
        Initialize recording window manager

        Args:
            vad: VoiceActivityDetector instance
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops (receives audio buffer)
        """
        self.vad = vad
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop

        self.is_recording = False
        self.recording_buffer = []

    def process_chunk(self, audio_chunk: np.ndarray):
        """
        Process audio chunk with VAD and manage recording

        Args:
            audio_chunk: Audio samples (int16, 16kHz)
        """
        # Run VAD
        vad_result = self.vad.process_chunk(audio_chunk)

        # Handle recording state
        if vad_result['speech_started'] and not self.is_recording:
            # Start recording
            self.is_recording = True
            self.recording_buffer = []
            logger.info("🔴 Recording started")
            if self.on_recording_start:
                self.on_recording_start()

        if self.is_recording:
            # Add to buffer
            self.recording_buffer.append(audio_chunk)

        if vad_result['speech_ended'] and self.is_recording:
            # Stop recording
            self.is_recording = False

            # Concatenate buffer
            if self.recording_buffer:
                full_recording = np.concatenate(self.recording_buffer)
                logger.info(f"⏹️ Recording stopped ({len(full_recording)/16000:.2f}s)")

                if self.on_recording_stop:
                    self.on_recording_stop(full_recording)

            self.recording_buffer = []

    def reset(self):
        """Reset recording state"""
        self.is_recording = False
        self.recording_buffer = []
        self.vad.reset()
