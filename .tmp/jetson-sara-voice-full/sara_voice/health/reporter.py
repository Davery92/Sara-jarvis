"""Periodic health reporter to Sara backend.

Reports GPU temperature, VRAM usage, uptime, and service state
to /api/sensory/jetson/health with 60s interval.
"""

import asyncio
import logging
import time

import psutil

logger = logging.getLogger(__name__)


class HealthReporter:
    """Reports Jetson system health to Sara backend."""

    def __init__(self, config: dict, event_reporter, gpu_manager):
        health_cfg = config.get("health", {})
        self._interval = health_cfg.get("report_interval_seconds", 60)
        self._event_reporter = event_reporter
        self._gpu_manager = gpu_manager
        self._start_time = time.time()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start periodic health reporting."""
        self._running = True
        self._start_time = time.time()
        self._task = asyncio.create_task(self._report_loop())
        logger.info("Health reporter started (interval=%ds)", self._interval)

    async def _report_loop(self):
        """Periodically send health data to backend."""
        while self._running:
            try:
                health = self._collect_health()
                await self._event_reporter.report_health(health)
                logger.debug("Health reported: GPU %d°C, VRAM %dMB/%dMB",
                             health.get("gpu_temperature_c", 0),
                             health.get("gpu_memory_used_mb", 0),
                             health.get("gpu_memory_total_mb", 0))
            except Exception:
                logger.exception("Health report failed")

            await asyncio.sleep(self._interval)

    def _collect_health(self) -> dict:
        """Collect current system health metrics."""
        gpu_stats = self._gpu_manager.get_stats()

        return {
            "uptime_seconds": time.time() - self._start_time,
            "cpu_percent": psutil.cpu_percent(interval=0),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_used_mb": psutil.virtual_memory().used // (1024 * 1024),
            "gpu_available": gpu_stats.get("gpu_available", False),
            "gpu_temperature_c": gpu_stats.get("temperature_c", 0),
            "gpu_memory_total_mb": gpu_stats.get("memory_total_mb", 0),
            "gpu_memory_used_mb": gpu_stats.get("memory_used_mb", 0),
            "gpu_memory_free_mb": gpu_stats.get("memory_free_mb", 0),
            "gpu_utilization_pct": gpu_stats.get("utilization_pct", 0),
            "service_state": "running",
        }

    def get_health(self) -> dict:
        """Get current health data (synchronous)."""
        return self._collect_health()

    async def stop(self):
        """Stop health reporting."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health reporter stopped")
