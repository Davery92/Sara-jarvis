"""
Audio Capture System
Real-time microphone capture with callback-based processing
"""
import numpy as np
import sounddevice as sd
import logging
from typing import Callable, Optional
from queue import Queue, Empty
import threading

logger = logging.getLogger(__name__)


class AudioCapture:
    """Real-time audio capture from microphone"""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = 'int16',
        blocksize: int = 1280,  # 80ms at 16kHz
        device: Optional[int] = None
    ):
        """
        Initialize audio capture

        Args:
            sample_rate: Sample rate in Hz (default 16kHz for wake word)
            channels: Number of audio channels (default 1 - mono)
            dtype: Audio data type (default int16)
            blocksize: Number of frames per callback (default 1280 = 80ms at 16kHz)
            device: Audio device index (None = default device)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self.device = device

        self.stream: Optional[sd.InputStream] = None
        self.is_running = False
        self.audio_queue = Queue(maxsize=100)  # Buffer up to 100 chunks

        # Callback for processing audio
        self.audio_callback: Optional[Callable] = None

        logger.info(
            f"Audio capture initialized: {sample_rate}Hz, {channels}ch, "
            f"{dtype}, blocksize={blocksize} ({blocksize/sample_rate*1000:.1f}ms)"
        )

    def set_callback(self, callback: Callable[[np.ndarray], None]):
        """
        Set callback function for audio processing

        Args:
            callback: Function that receives audio chunks (numpy array)
        """
        self.audio_callback = callback

    def _stream_callback(self, indata, frames, time_info, status):
        """Internal callback for sounddevice stream"""
        if status:
            logger.warning(f"Audio stream status: {status}")

        # Copy data (sounddevice reuses buffer)
        audio_chunk = indata.copy()

        # Put in queue for processing thread
        try:
            self.audio_queue.put_nowait(audio_chunk)
        except:
            # Queue full, drop oldest
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(audio_chunk)
            except:
                pass

    def _processing_thread(self):
        """Thread that processes audio from queue"""
        logger.debug("Audio processing thread started")

        while self.is_running:
            try:
                # Get audio chunk from queue (timeout to allow checking is_running)
                audio_chunk = self.audio_queue.get(timeout=0.1)

                # Flatten if multi-channel
                if len(audio_chunk.shape) > 1:
                    audio_chunk = audio_chunk[:, 0]

                # Convert to int16 if needed
                if audio_chunk.dtype == np.float32:
                    audio_chunk = (audio_chunk * 32767).astype(np.int16)

                # Call user callback
                if self.audio_callback:
                    self.audio_callback(audio_chunk)

            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing audio: {e}")

        logger.debug("Audio processing thread stopped")

    def start(self):
        """Start capturing audio"""
        if self.is_running:
            logger.warning("Audio capture already running")
            return

        logger.info("Starting audio capture...")

        # Start processing thread
        self.is_running = True
        self.processing_thread = threading.Thread(
            target=self._processing_thread,
            daemon=True
        )
        self.processing_thread.start()

        # Start audio stream
        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.blocksize,
                device=self.device,
                callback=self._stream_callback
            )
            self.stream.start()
            logger.info("✅ Audio capture started")

        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}")
            self.is_running = False
            raise

    def stop(self):
        """Stop capturing audio"""
        if not self.is_running:
            return

        logger.info("Stopping audio capture...")
        self.is_running = False

        # Stop stream
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Wait for processing thread
        if hasattr(self, 'processing_thread'):
            self.processing_thread.join(timeout=1.0)

        logger.info("Audio capture stopped")

    def list_devices(self):
        """List available audio devices"""
        devices = sd.query_devices()
        logger.info("Available audio devices:")
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                logger.info(
                    f"  [{i}] {dev['name']} "
                    f"({dev['max_input_channels']} channels, {dev['default_samplerate']}Hz)"
                )
        return devices

    def test_microphone(self, duration_seconds: float = 3.0):
        """
        Test microphone by recording and showing volume levels

        Args:
            duration_seconds: How long to test
        """
        import time

        logger.info(f"Testing microphone for {duration_seconds} seconds...")
        logger.info("Speak into the microphone!")

        volumes = []

        def test_callback(audio_chunk):
            # Calculate RMS volume
            rms = np.sqrt(np.mean(audio_chunk.astype(float) ** 2))
            volumes.append(rms)

            # Visual volume meter
            bars = int(rms / 1000)
            meter = "█" * min(bars, 50)
            print(f"\rVolume: {meter:<50} {rms:.0f}", end="")

        self.set_callback(test_callback)
        self.start()

        time.sleep(duration_seconds)

        self.stop()
        print()  # New line after meter

        if volumes:
            avg_volume = np.mean(volumes)
            max_volume = np.max(volumes)
            logger.info(f"✅ Microphone test complete")
            logger.info(f"   Average volume: {avg_volume:.0f}")
            logger.info(f"   Peak volume: {max_volume:.0f}")

            if avg_volume < 100:
                logger.warning("⚠️  Volume very low - check microphone settings")
            elif avg_volume > 20000:
                logger.warning("⚠️  Volume very high - may cause clipping")
        else:
            logger.error("❌ No audio captured - check microphone permissions")
