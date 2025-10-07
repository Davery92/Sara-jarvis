"""
Wake Word Detection using openWakeWord
Detects "sarah" wake word with configurable sensitivity
"""
import numpy as np
import time
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """openWakeWord-based wake word detector"""

    def __init__(
        self,
        model_path: Optional[str] = None,
        threshold: float = 0.5,
        debounce_seconds: float = 1.5,
        sample_rate: int = 16000
    ):
        """
        Initialize wake word detector

        Args:
            model_path: Path to .tflite model file (default: models/sarah.tflite)
            threshold: Detection threshold 0-1 (default 0.5)
            debounce_seconds: Minimum time between detections (default 1.5s)
            sample_rate: Audio sample rate (must be 16kHz for openWakeWord)
        """
        try:
            from openwakeword.model import Model
        except ImportError:
            raise ImportError(
                "openwakeword not installed. Run: pip install openwakeword"
            )

        if sample_rate != 16000:
            raise ValueError("openWakeWord requires 16kHz sample rate")

        self.threshold = threshold
        self.debounce_seconds = debounce_seconds
        self.last_detection_time = 0
        self.sample_rate = sample_rate

        # Determine model path
        if model_path is None:
            # Default to sarah model in models/ directory
            # Try ONNX first (Windows), then TFLite (Linux/Mac)
            agent_root = Path(__file__).parent.parent
            onnx_path = agent_root / "models" / "sarah.onnx"
            tflite_path = agent_root / "models" / "sarah.tflite"

            if onnx_path.exists():
                model_path = onnx_path
                logger.info("Found ONNX model (Windows compatible)")
            elif tflite_path.exists():
                model_path = tflite_path
                logger.info("Found TFLite model")
            else:
                model_path = None

        self.model_path = Path(model_path) if model_path else None

        # Check if custom model exists
        if not self.model_path or not self.model_path.exists():
            if self.model_path:
                logger.warning(f"Custom model not found at {self.model_path}")
            logger.info("Will use pre-trained 'hey_mycroft' model for testing")
            # Use built-in model for now
            self.model = Model(wakeword_models=["hey_mycroft"])
            self.wake_word_name = "hey_mycroft"
        else:
            logger.info(f"Loading custom wake word model: {self.model_path}")
            self.model = Model(wakeword_models=[str(self.model_path)])
            self.wake_word_name = self.model_path.stem  # "sarah"

        logger.info(
            f"Wake word detector initialized: '{self.wake_word_name}' "
            f"(threshold={threshold}, debounce={debounce_seconds}s)"
        )

    def process_chunk(self, audio_chunk: np.ndarray) -> Optional[Dict]:
        """
        Process audio chunk and check for wake word

        Args:
            audio_chunk: Audio samples (int16, 16kHz)
                        Should be 80ms chunks (1280 samples) for best performance

        Returns:
            Detection dict if wake word detected, else None
            {
                "name": "sarah",
                "score": 0.87,
                "timestamp": 1234567890.123
            }
        """
        # Ensure correct dtype
        if audio_chunk.dtype != np.int16:
            audio_chunk = audio_chunk.astype(np.int16)

        # Predict on chunk
        prediction = self.model.predict(audio_chunk)

        # Check all loaded models
        for model_name, score in prediction.items():
            if score > self.threshold:
                # Check debounce
                current_time = time.time()
                if current_time - self.last_detection_time >= self.debounce_seconds:
                    logger.info(
                        f"🎤 Wake word '{model_name}' detected! (score: {score:.2f})"
                    )
                    self.last_detection_time = current_time

                    return {
                        "name": model_name,
                        "score": float(score),
                        "timestamp": current_time
                    }
                else:
                    # Within debounce window
                    logger.debug(
                        f"Wake word detected but debounced (score: {score:.2f})"
                    )

        return None

    def reset_debounce(self):
        """Reset debounce timer (useful after processing an utterance)"""
        self.last_detection_time = 0

    def set_threshold(self, threshold: float):
        """Dynamically adjust detection threshold"""
        if not 0 <= threshold <= 1:
            raise ValueError("Threshold must be between 0 and 1")
        self.threshold = threshold
        logger.info(f"Wake word threshold updated to {threshold}")
