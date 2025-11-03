"""
Voice Activity Detection using WebRTC VAD (Lightweight)
Detects speech start/stop for clean recording windows
"""
import numpy as np
import logging
from typing import Optional, Callable
import webrtcvad

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """WebRTC VAD-based voice activity detector (lightweight, no PyTorch)"""

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,  # Not used in WebRTC VAD, kept for compatibility
        min_speech_duration_ms: int = 200,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30,
        aggressiveness: int = 2  # WebRTC VAD aggressiveness (0-3, higher = more aggressive)
    ):
        """
        Initialize VAD using WebRTC VAD (lightweight alternative to Silero)

        Args:
            sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
            threshold: Kept for compatibility, not used in WebRTC VAD
            min_speech_duration_ms: Minimum speech duration to trigger (default 200ms)
            min_silence_duration_ms: Silence duration to end speech (default 500ms)
            speech_pad_ms: Padding before/after speech (default 30ms)
            aggressiveness: WebRTC VAD mode 0-3 (0=least aggressive, 3=most aggressive)
        """
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("WebRTC VAD requires sample rate of 8000, 16000, 32000, or 48000")

        self.sample_rate = sample_rate
        self.threshold = threshold  # Not used, kept for compatibility
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.aggressiveness = aggressiveness

        # Initialize WebRTC VAD
        try:
            logger.info(f"Loading WebRTC VAD (aggressiveness={aggressiveness})...")
            self.vad = webrtcvad.Vad(aggressiveness)
            logger.info("✅ WebRTC VAD loaded")
        except Exception as e:
            logger.error(f"Failed to load WebRTC VAD: {e}")
            raise

        # State tracking
        self.is_speech = False
        self.speech_frames = 0  # Consecutive speech frames
        self.silence_frames = 0  # Consecutive silence frames

        # WebRTC VAD processes 10ms, 20ms, or 30ms frames
        self.frame_duration_ms = 30  # Use 30ms frames
        self.frame_samples = int(sample_rate * self.frame_duration_ms / 1000)

        # Calculate frame thresholds
        self.min_speech_frames = max(1, int(min_speech_duration_ms / self.frame_duration_ms))
        self.min_silence_frames = max(1, int(min_silence_duration_ms / self.frame_duration_ms))

    def process_chunk(self, audio_chunk: np.ndarray) -> dict:
        """
        Process audio chunk and detect speech activity

        Args:
            audio_chunk: Audio samples (int16, matching sample_rate)
                        Can be any size - will be split into 30ms frames

        Returns:
            dict with:
                - is_speech: bool (currently speaking)
                - speech_started: bool (speech just started)
                - speech_ended: bool (speech just ended)
                - probability: float (1.0 if speech, 0.0 if silence - binary for WebRTC)
        """
        # Ensure int16 format
        if audio_chunk.dtype != np.int16:
            audio_chunk = audio_chunk.astype(np.int16)

        # WebRTC VAD requires exact frame sizes (10ms, 20ms, or 30ms)
        # We use 30ms frames
        frame_size = self.frame_samples

        # Process ALL frames in the chunk (not just the first one!)
        # This is critical - audio capture sends 80ms chunks but VAD needs 30ms frames
        speech_started = False
        speech_ended = False

        # Split chunk into 30ms frames and process each one
        num_frames = len(audio_chunk) // frame_size
        remaining_samples = len(audio_chunk) % frame_size

        for i in range(num_frames):
            frame = audio_chunk[i * frame_size:(i + 1) * frame_size]
            result = self._process_frame(frame)

            # Aggregate results - if any frame triggers state change, propagate it
            if result['speech_started']:
                speech_started = True
            if result['speech_ended']:
                speech_ended = True

        # Process remaining samples (if any) by padding to frame_size
        if remaining_samples > 0:
            last_frame = audio_chunk[-remaining_samples:]
            padded = np.zeros(frame_size, dtype=np.int16)
            padded[:remaining_samples] = last_frame
            result = self._process_frame(padded)
            if result['speech_started']:
                speech_started = True
            if result['speech_ended']:
                speech_ended = True

        return {
            'is_speech': self.is_speech,
            'speech_started': speech_started,
            'speech_ended': speech_ended,
            'probability': 1.0 if self.is_speech else 0.0
        }

    def _process_frame(self, frame: np.ndarray) -> dict:
        """
        Process a single 30ms frame

        Args:
            frame: Exactly frame_samples (480 for 16kHz) of int16 audio

        Returns:
            dict with speech_started and speech_ended flags
        """
        # WebRTC VAD requires bytes
        audio_bytes = frame.tobytes()

        # Get speech detection (binary: True/False)
        try:
            is_speech_frame = self.vad.is_speech(audio_bytes, self.sample_rate)
        except Exception as e:
            logger.warning(f"VAD processing error: {e}, frame size: {len(frame)}")
            is_speech_frame = False

        # Track state changes
        speech_started = False
        speech_ended = False

        # Update frame counters
        if is_speech_frame:
            self.speech_frames += 1
            self.silence_frames = 0

            # Debug: Show speech frame detection
            if self.speech_frames % 10 == 1:  # Log every 10th frame to avoid spam
                logger.debug(f"VAD: Speech frame {self.speech_frames}/{self.min_speech_frames} needed")

            # Check if speech started
            if not self.is_speech and self.speech_frames >= self.min_speech_frames:
                self.is_speech = True
                speech_started = True
                logger.info(f"🎤 Speech started (after {self.speech_frames} frames)")
        else:
            self.silence_frames += 1
            self.speech_frames = 0

            # Debug: Show silence detection during recording
            if self.is_speech and self.silence_frames % 10 == 1:  # Log every 10th silence frame
                logger.debug(f"VAD: Silence frame {self.silence_frames}/{self.min_silence_frames} needed")

            # Check if speech ended
            if self.is_speech and self.silence_frames >= self.min_silence_frames:
                self.is_speech = False
                speech_ended = True
                logger.info(f"🔇 Speech ended (after {self.silence_frames} silence frames)")

        return {
            'speech_started': speech_started,
            'speech_ended': speech_ended
        }

    def reset(self):
        """Reset VAD state"""
        self.is_speech = False
        self.speech_frames = 0
        self.silence_frames = 0
        logger.debug("VAD reset")

    def set_threshold(self, threshold: float):
        """Kept for compatibility - WebRTC VAD uses aggressiveness instead"""
        logger.info(f"Note: WebRTC VAD doesn't use threshold. Use aggressiveness (0-3) instead.")


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
            audio_chunk: Audio samples (int16, matching sample_rate)
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

    def force_start_recording(self):
        """Force recording to start immediately (for wake word mode)"""
        if not self.is_recording:
            self.is_recording = True
            self.recording_buffer = []
            logger.debug("🔴 Recording force-started (wake word mode)")

    def add_to_buffer(self, audio_data: np.ndarray):
        """Add audio data directly to recording buffer"""
        if self.is_recording:
            self.recording_buffer.append(audio_data)
            logger.debug(f"Added {len(audio_data)} samples to buffer")
