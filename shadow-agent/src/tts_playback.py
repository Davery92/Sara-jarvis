"""
TTS Audio Playback
Plays synthesized speech from Sara with echo suppression
"""
import sounddevice as sd
import numpy as np
import wave
import io
import logging
from typing import Optional, Callable
import threading
import time

logger = logging.getLogger(__name__)


class TTSPlayer:
    """Handles TTS audio playback with echo suppression"""

    def __init__(
        self,
        sample_rate: int = 22050,
        on_playback_start: Optional[Callable] = None,
        on_playback_end: Optional[Callable] = None
    ):
        """
        Initialize TTS player

        Args:
            sample_rate: TTS audio sample rate (typically 22050 or 24000)
            on_playback_start: Callback when playback starts
            on_playback_end: Callback when playback ends
        """
        self.sample_rate = sample_rate
        self.on_playback_start = on_playback_start
        self.on_playback_end = on_playback_end

        self.is_playing = False
        self.playback_thread: Optional[threading.Thread] = None
        self.stop_requested = False

    def play_audio_bytes(self, audio_bytes: bytes):
        """
        Play audio from bytes (WAV format)

        Args:
            audio_bytes: WAV audio data
        """
        # Stop any current playback
        self.stop()

        # Start playback in thread
        self.playback_thread = threading.Thread(
            target=self._playback_worker,
            args=(audio_bytes,),
            daemon=True
        )
        self.playback_thread.start()

    def _playback_worker(self, audio_bytes: bytes):
        """Worker thread for audio playback"""
        try:
            # Parse WAV file
            wav_buffer = io.BytesIO(audio_bytes)
            with wave.open(wav_buffer, 'rb') as wav_file:
                # Get audio parameters
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                framerate = wav_file.getframerate()
                n_frames = wav_file.getnframes()

                # Read audio data
                audio_data = wav_file.readframes(n_frames)

            # Convert to numpy array
            if sample_width == 2:  # 16-bit
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
            elif sample_width == 1:  # 8-bit
                audio_array = np.frombuffer(audio_data, dtype=np.uint8)
                audio_array = ((audio_array.astype(np.float32) - 128) * 256).astype(np.int16)
            else:
                logger.error(f"Unsupported sample width: {sample_width}")
                return

            # Reshape if stereo
            if channels == 2:
                audio_array = audio_array.reshape(-1, 2)
            elif channels == 1:
                audio_array = audio_array.reshape(-1, 1)

            # Start playback
            logger.info(f"🔊 Playing TTS audio ({len(audio_array)/framerate:.2f}s)")
            self.is_playing = True
            self.stop_requested = False

            if self.on_playback_start:
                self.on_playback_start()

            # Play audio
            sd.play(audio_array, samplerate=framerate, blocking=True)

            # Wait for playback to finish (or be interrupted)
            while sd.get_stream().active and not self.stop_requested:
                time.sleep(0.01)

            if self.stop_requested:
                sd.stop()
                logger.info("🛑 Playback interrupted (barge-in)")
            else:
                logger.info("✅ Playback complete")

        except Exception as e:
            logger.error(f"Error during playback: {e}")

        finally:
            self.is_playing = False
            if self.on_playback_end:
                self.on_playback_end()

    def stop(self):
        """Stop current playback (for barge-in)"""
        if self.is_playing:
            logger.debug("Stopping playback...")
            self.stop_requested = True
            sd.stop()

            # Wait for thread to finish
            if self.playback_thread:
                self.playback_thread.join(timeout=1.0)

    def is_currently_playing(self) -> bool:
        """Check if audio is currently playing"""
        return self.is_playing


class EchoSuppressor:
    """
    Manages echo suppression during TTS playback
    Mutes microphone input while Sara is speaking
    """

    def __init__(self, audio_capture):
        """
        Initialize echo suppressor

        Args:
            audio_capture: AudioCapture instance to control
        """
        self.audio_capture = audio_capture
        self.original_callback = None
        self.suppression_active = False

    def start_suppression(self):
        """Start echo suppression (mute mic processing)"""
        if not self.suppression_active:
            logger.debug("🔇 Echo suppression activated")
            # Save original callback
            self.original_callback = self.audio_capture.audio_callback
            # Set to None to stop processing
            self.audio_capture.audio_callback = None
            self.suppression_active = True

    def stop_suppression(self):
        """Stop echo suppression (resume mic processing)"""
        if self.suppression_active:
            logger.debug("🔊 Echo suppression deactivated")
            # Restore original callback
            if self.original_callback:
                self.audio_capture.audio_callback = self.original_callback
            self.suppression_active = False

            # Add small delay to avoid feedback
            time.sleep(0.3)

    def is_active(self) -> bool:
        """Check if echo suppression is currently active"""
        return self.suppression_active
