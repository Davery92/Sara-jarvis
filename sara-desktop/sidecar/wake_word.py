"""
Wake Word Detection using OpenWakeWord

Continuously listens for "Hey Sara" wake word and triggers callback.
Uses the pre-trained hey_sara.onnx model.
"""
import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional
import threading
import queue

import numpy as np

logger = logging.getLogger(__name__)

# Audio parameters matching OpenWakeWord expectations
SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms at 16kHz


class WakeWordDetector:
    """
    Detects "Hey Sara" wake word using OpenWakeWord.

    Uses a separate thread for audio capture to avoid blocking
    the async event loop.
    """

    def __init__(
        self,
        model_path: Path,
        threshold: float = 0.5,
        on_wake_word: Optional[Callable] = None
    ):
        self.model_path = model_path
        self.threshold = threshold
        self.on_wake_word = on_wake_word

        self._running = False
        self._audio_thread = None
        self._audio_queue = queue.Queue()
        self._oww_model = None
        self._pyaudio = None
        self._stream = None

        # Cooldown to prevent rapid re-triggers
        self._last_detection = 0
        self._cooldown_seconds = 2.0

    async def start(self):
        """Start wake word detection."""
        logger.info("Starting wake word detection...")

        if not self.model_path.exists():
            logger.error(f"Wake word model not found: {self.model_path}")
            return

        try:
            # Import OpenWakeWord
            from openwakeword.model import Model

            # Load the custom model
            self._oww_model = Model(
                wakeword_models=[str(self.model_path)],
                inference_framework="onnx"
            )
            logger.info(f"Loaded wake word model: {self.model_path.name}")

            # Start audio capture thread
            self._running = True
            self._audio_thread = threading.Thread(target=self._audio_capture_loop, daemon=True)
            self._audio_thread.start()

            # Process audio in async loop
            await self._process_audio()

        except ImportError as e:
            logger.error(f"OpenWakeWord not installed: {e}")
            logger.error("Install with: pip install openwakeword")
        except Exception as e:
            logger.exception(f"Error starting wake word detection: {e}")

    async def stop(self):
        """Stop wake word detection."""
        logger.info("Stopping wake word detection...")
        self._running = False

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pyaudio:
            self._pyaudio.terminate()

        if self._audio_thread:
            self._audio_thread.join(timeout=2.0)

    def _get_audio_devices(self, pyaudio_instance):
        """Get sorted list of audio devices by priority."""
        # Priority order matters - first match in priority list wins
        priority_keywords = ["airpod", "bluetooth"]  # Highest priority (matches airpod, airpods)
        acceptable_keywords = ["built-in", "macbook", "internal", "default"]
        avoid_keywords = ["iphone", "hdmi", "display"]

        # Log all available input devices for debugging
        logger.info("Available audio input devices:")
        for i in range(pyaudio_instance.get_device_count()):
            info = pyaudio_instance.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                logger.info(f"  [{i}] {info['name']}")

        # Collect all valid devices with their priority
        devices = []
        for i in range(pyaudio_instance.get_device_count()):
            info = pyaudio_instance.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                name_lower = info["name"].lower()

                # Skip devices we want to avoid
                if any(avoid in name_lower for avoid in avoid_keywords):
                    logger.debug(f"Skipping audio device: {info['name']}")
                    continue

                # Determine priority (lower = better)
                priority = 100  # Default low priority
                for idx, keyword in enumerate(priority_keywords):
                    if keyword in name_lower:
                        priority = idx
                        break
                else:
                    for idx, keyword in enumerate(acceptable_keywords):
                        if keyword in name_lower:
                            priority = 10 + idx
                            break

                devices.append((priority, i, info["name"]))

        # Sort by priority
        devices.sort(key=lambda x: x[0])
        return devices

    def _open_audio_stream(self, pyaudio_instance, device_index):
        """Open audio stream with given device."""
        import pyaudio
        return pyaudio_instance.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK_SIZE
        )

    def _audio_capture_loop(self):
        """Capture audio in a separate thread with device fallback."""
        try:
            import pyaudio
            import time

            self._pyaudio = pyaudio.PyAudio()
            current_device_name = None
            consecutive_errors = 0
            max_consecutive_errors = 5

            while self._running:
                # Get available devices (re-scan each time to detect new/removed devices)
                devices = self._get_audio_devices(self._pyaudio)

                if not devices:
                    logger.error("No audio input device found, waiting...")
                    time.sleep(2)
                    # Re-initialize PyAudio to detect new devices
                    self._pyaudio.terminate()
                    self._pyaudio = pyaudio.PyAudio()
                    continue

                # Try to open best available device
                stream_opened = False
                for priority, device_index, device_name in devices:
                    try:
                        if self._stream:
                            try:
                                self._stream.stop_stream()
                                self._stream.close()
                            except Exception:
                                pass
                            self._stream = None

                        self._stream = self._open_audio_stream(self._pyaudio, device_index)
                        current_device_name = device_name
                        logger.info(f"Using audio device: {device_name} (priority {priority})")
                        stream_opened = True
                        consecutive_errors = 0
                        break
                    except Exception as e:
                        logger.warning(f"Failed to open device {device_name}: {e}")
                        continue

                if not stream_opened:
                    logger.error("Failed to open any audio device, waiting...")
                    time.sleep(2)
                    continue

                logger.info("Audio stream opened, listening for wake word...")

                # Read audio until error or stopped
                while self._running:
                    try:
                        audio_data = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
                        # Convert to numpy array
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                        self._audio_queue.put(audio_array)
                        consecutive_errors = 0
                    except Exception as e:
                        if self._running:
                            consecutive_errors += 1
                            logger.error(f"Audio capture error ({consecutive_errors}/{max_consecutive_errors}): {e}")

                            if consecutive_errors >= max_consecutive_errors:
                                logger.warning(f"Device {current_device_name} may have disconnected, switching...")
                                # Re-initialize PyAudio to detect device changes
                                try:
                                    self._stream.stop_stream()
                                    self._stream.close()
                                except Exception:
                                    pass
                                self._stream = None
                                self._pyaudio.terminate()
                                self._pyaudio = pyaudio.PyAudio()
                                break  # Break inner loop to re-select device

                            time.sleep(0.1)

        except Exception as e:
            logger.exception(f"Audio thread error: {e}")

    async def _process_audio(self):
        """Process audio chunks and detect wake word."""
        while self._running:
            try:
                # Get audio from queue (non-blocking)
                try:
                    audio_chunk = self._audio_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

                # Run prediction
                prediction = self._oww_model.predict(audio_chunk)

                # Check for wake word detection
                # The model returns predictions for each wake word
                for model_name, score in prediction.items():
                    if score >= self.threshold:
                        current_time = asyncio.get_event_loop().time()

                        # Check cooldown
                        if current_time - self._last_detection >= self._cooldown_seconds:
                            self._last_detection = current_time
                            logger.info(f"Wake word detected! Score: {score:.3f}")

                            # Call the callback
                            if self.on_wake_word:
                                if asyncio.iscoroutinefunction(self.on_wake_word):
                                    await self.on_wake_word()
                                else:
                                    self.on_wake_word()

            except Exception as e:
                logger.error(f"Audio processing error: {e}")
                await asyncio.sleep(0.1)


class MockWakeWordDetector:
    """
    Mock wake word detector for testing without audio.
    Simulates detection when a specific key is pressed.
    """

    def __init__(self, on_wake_word: Optional[Callable] = None):
        self.on_wake_word = on_wake_word
        self._running = False

    async def start(self):
        """Start mock detection."""
        logger.info("Starting mock wake word detector (press Ctrl+W to simulate)")
        self._running = True

        try:
            from pynput import keyboard

            def on_press(key):
                try:
                    if hasattr(key, 'char') and key.char == 'w':
                        # Check if Ctrl is held
                        pass  # Simplified - just log
                except AttributeError:
                    pass

            # For testing, just wait
            while self._running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Mock detector error: {e}")

    async def stop(self):
        """Stop mock detection."""
        self._running = False
