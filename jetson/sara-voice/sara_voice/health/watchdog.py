"""systemd watchdog integration.

Sends periodic sd_notify watchdog heartbeats to systemd.
If the heartbeat stops, systemd will restart the service.
"""

import asyncio
import logging
import os
import socket

logger = logging.getLogger(__name__)


class SystemdWatchdog:
    """Sends watchdog heartbeats to systemd."""

    def __init__(self, config: dict):
        health_cfg = config.get("health", {})
        self._interval = health_cfg.get("watchdog_interval_seconds", 30)
        self._task: asyncio.Task | None = None
        self._running = False
        self._socket_path = os.environ.get("NOTIFY_SOCKET", "")

    def _sd_notify(self, state: str):
        """Send notification to systemd."""
        if not self._socket_path:
            return  # Not running under systemd

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            if self._socket_path.startswith("@"):
                addr = "\0" + self._socket_path[1:]
            else:
                addr = self._socket_path
            sock.sendto(state.encode(), addr)
            sock.close()
        except Exception as e:
            logger.debug("sd_notify failed: %s", e)

    async def start(self):
        """Start watchdog heartbeat loop."""
        self._running = True
        self._sd_notify("READY=1")
        logger.info("systemd watchdog started (interval=%ds, socket=%s)",
                     self._interval, self._socket_path or "none")
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """Periodically ping systemd watchdog."""
        while self._running:
            self._sd_notify("WATCHDOG=1")
            await asyncio.sleep(self._interval)

    def notify_stopping(self):
        """Notify systemd that we're stopping."""
        self._sd_notify("STOPPING=1")

    def notify_status(self, status: str):
        """Set systemd status string."""
        self._sd_notify(f"STATUS={status}")

    async def stop(self):
        """Stop watchdog."""
        self._running = False
        self.notify_stopping()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("systemd watchdog stopped")
