"""GPU priority queue for coordinating GPU-bound tasks.

P0: Wake word + VAD (CPU — always available, no GPU contention)
P1: Face detection (GPU, every 5s)
P2: Local STT fallback (GPU, on demand)

Uses asyncio.Lock to prevent concurrent GPU operations.
Face detection pauses during local STT to avoid contention.
"""

import asyncio
import logging
import time
from enum import IntEnum

logger = logging.getLogger(__name__)


class GPUPriority(IntEnum):
    """GPU task priority levels. Lower = higher priority."""
    FACE_DETECTION = 1   # P1: periodic, can wait
    LOCAL_STT = 2        # P2: on-demand, user-facing latency


class GPUPriorityQueue:
    """Coordinates GPU access between concurrent tasks."""

    def __init__(self, config: dict):
        self._lock = asyncio.Lock()
        self._current_task: str | None = None
        self._current_priority: GPUPriority | None = None
        self._wait_count = 0
        self._total_wait_ms = 0.0

    async def acquire(self, task_name: str, priority: GPUPriority) -> bool:
        """Acquire GPU access. Blocks until available.

        Returns True if acquired, False on timeout.
        """
        start = time.monotonic()

        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("GPU acquire timeout for %s (P%d)", task_name, priority)
            return False

        wait_ms = (time.monotonic() - start) * 1000
        if wait_ms > 10:
            self._wait_count += 1
            self._total_wait_ms += wait_ms
            logger.debug(
                "GPU acquired by %s (P%d) after %.1fms wait",
                task_name, priority, wait_ms,
            )

        self._current_task = task_name
        self._current_priority = priority
        return True

    def release(self, task_name: str):
        """Release GPU access."""
        if self._lock.locked():
            self._current_task = None
            self._current_priority = None
            self._lock.release()

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    @property
    def current_task(self) -> str | None:
        return self._current_task

    @property
    def stats(self) -> dict:
        return {
            "is_busy": self.is_busy,
            "current_task": self._current_task,
            "wait_count": self._wait_count,
            "avg_wait_ms": (
                self._total_wait_ms / self._wait_count
                if self._wait_count > 0
                else 0.0
            ),
        }
