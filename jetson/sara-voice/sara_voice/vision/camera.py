"""OBSBOT Tiny 4K camera capture via OpenCV V4L2.

Captures frames at 720p@15fps for face detection.
Uses V4L2 backend for direct device access on Jetson.
"""

import logging
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraCapture:
    """Captures frames from OBSBOT camera via V4L2."""

    def __init__(self, config: dict):
        vision_cfg = config.get("vision", {})
        self._device = vision_cfg.get("camera_device", 0)
        self._camera_name = vision_cfg.get("camera_name", "OBSBOT")
        self._resolution = tuple(vision_cfg.get("resolution", [1280, 720]))
        self._fps = vision_cfg.get("fps", 15)

        self._cap: cv2.VideoCapture | None = None
        self._running = False
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._capture_thread: threading.Thread | None = None
        self._frame_count = 0

    def _find_camera(self) -> int:
        """Find the camera device index."""
        # Try specified device first
        cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if cap.isOpened():
            name = cap.getBackendName()
            cap.release()
            logger.info("Camera found at device %d (%s)", self._device, name)
            return self._device

        # Search for camera by trying indices 0-9
        for idx in range(10):
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.release()
                logger.info("Camera found at device %d", idx)
                return idx

        raise RuntimeError("No camera device found")

    def start(self):
        """Start camera capture in background thread."""
        if self._running:
            return

        device_idx = self._find_camera()
        self._cap = cv2.VideoCapture(device_idx, cv2.CAP_V4L2)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

        # Verify settings
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
        logger.info("Camera opened: %dx%d @ %.1ffps", actual_w, actual_h, actual_fps)

        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def _capture_loop(self):
        """Background thread that continuously captures frames."""
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Frame capture failed, retrying...")
                time.sleep(0.1)
                continue

            with self._frame_lock:
                self._latest_frame = frame
                self._frame_count += 1

            # Throttle to target FPS
            time.sleep(1.0 / self._fps)

    def get_frame(self) -> np.ndarray | None:
        """Get the latest captured frame (BGR numpy array)."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def stop(self):
        """Stop camera capture."""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("Camera capture stopped (total frames: %d)", self._frame_count)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def frame_count(self) -> int:
        return self._frame_count
