"""
Pre-Roll Audio Buffer
Circular buffer that maintains the last N seconds of audio
for including speech before wake word detection
"""
import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class PreRollBuffer:
    """Circular buffer for pre-roll audio capture"""

    def __init__(self, duration_seconds: float = 1.5, sample_rate: int = 16000):
        """
        Args:
            duration_seconds: How much audio to buffer (default 1.5s)
            sample_rate: Audio sample rate in Hz (default 16kHz)
        """
        self.sample_rate = sample_rate
        self.duration_seconds = duration_seconds
        self.max_samples = int(sample_rate * duration_seconds)

        # Use deque with maxlen for automatic circular behavior
        self.buffer = deque(maxlen=self.max_samples)

        logger.info(f"Pre-roll buffer initialized: {duration_seconds}s @ {sample_rate}Hz = {self.max_samples} samples")

    def add_chunk(self, audio_chunk: np.ndarray):
        """
        Add audio chunk to buffer

        Args:
            audio_chunk: numpy array of audio samples (int16)
        """
        # Flatten if multi-channel
        if len(audio_chunk.shape) > 1:
            audio_chunk = audio_chunk[:, 0]

        # Add samples to buffer (automatically evicts old samples when full)
        for sample in audio_chunk:
            self.buffer.append(sample)

    def get_buffer(self) -> np.ndarray:
        """
        Get entire buffer contents as numpy array

        Returns:
            numpy array of buffered audio samples (int16)
        """
        return np.array(list(self.buffer), dtype=np.int16)

    def clear(self):
        """Clear the buffer"""
        self.buffer.clear()
        logger.debug("Pre-roll buffer cleared")

    def get_duration_seconds(self) -> float:
        """Get current buffer duration in seconds"""
        return len(self.buffer) / self.sample_rate

    def is_full(self) -> bool:
        """Check if buffer is at max capacity"""
        return len(self.buffer) >= self.max_samples
