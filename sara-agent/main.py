#!/usr/bin/env python3
"""
Sara Headless Agent - Main Entry Point

A headless background service that provides:
- System metrics collection (CPU, RAM, disk, network, GPU)
- WebSocket connection to Sara backend for commands
- Heartbeat reporting for device status

Designed for Linux servers without a GUI.
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
from typing import Optional

from config import config

# Set up logging
log_handlers = [logging.StreamHandler(sys.stdout)]

# Add file handler if log directory is writable
log_dir = config.log_file.parent
if log_dir.exists() or os.access(log_dir.parent, os.W_OK):
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_handlers.append(logging.FileHandler(config.log_file, mode="a"))
    except (PermissionError, OSError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=log_handlers
)
logger = logging.getLogger("sara-agent")


class HeadlessAgentService:
    """Main service that coordinates all headless agent components."""

    def __init__(self):
        self.running = False
        self._tasks = []

        # Component instances
        self._backend_client = None
        self._metrics_collector = None

    async def start(self):
        """Start all agent services."""
        logger.info("=" * 60)
        logger.info("Starting Sara Headless Agent")
        logger.info("=" * 60)
        logger.info(f"Device ID: {config.device_id}")
        logger.info(f"Hostname: {config.hostname}")
        logger.info(f"Platform: {config.platform_name}")
        logger.info(f"Backend: {config.backend_url}")
        logger.info(f"Agent Type: {config.agent_type}")

        self.running = True

        try:
            from backend_client import BackendClient
            from metrics import metrics_collector

            self._metrics_collector = metrics_collector

            self._backend_client = BackendClient(
                config=config,
                on_command=self._handle_command
            )

            # Start all services
            self._tasks = [
                asyncio.create_task(self._backend_client.connect()),
                asyncio.create_task(self._heartbeat_loop()),
                asyncio.create_task(self._metrics_loop()),
            ]

            logger.info("All services started successfully")

            # Wait for all tasks
            await asyncio.gather(*self._tasks, return_exceptions=True)

        except ImportError as e:
            logger.error(f"Failed to import component: {e}")
            logger.error("Make sure all dependencies are installed: pip install -r requirements.txt")
            raise
        except Exception as e:
            logger.exception(f"Error starting agent: {e}")
            raise

    async def stop(self):
        """Stop all agent services."""
        logger.info("Stopping Sara Headless Agent...")
        self.running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Stop components
        if self._backend_client:
            await self._backend_client.disconnect()

        logger.info("Agent stopped")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to backend."""
        # Wait for initial connection
        await asyncio.sleep(5)

        while self.running:
            try:
                if self._backend_client and self._backend_client.is_connected:
                    # Collect quick metrics for heartbeat
                    quick_metrics = None
                    if self._metrics_collector:
                        try:
                            full = self._metrics_collector.collect()
                            if full:
                                quick_metrics = {
                                    "cpu_percent": full.cpu.usage_percent,
                                    "memory_percent": full.memory.percent_used,
                                    "uptime_seconds": full.uptime_seconds,
                                }
                        except Exception as e:
                            logger.debug(f"Quick metrics error: {e}")

                    await self._backend_client.send_heartbeat(quick_metrics)

            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

            await asyncio.sleep(config.heartbeat_interval)

    async def _metrics_loop(self):
        """Send periodic full metrics to backend."""
        # Wait for initial connection and offset from heartbeat
        await asyncio.sleep(15)

        while self.running:
            try:
                if self._backend_client and self._backend_client.is_connected:
                    if self._metrics_collector:
                        metrics = self._metrics_collector.collect()
                        if metrics:
                            await self._backend_client.send_metrics(metrics.to_dict())

            except Exception as e:
                logger.error(f"Metrics error: {e}")

            await asyncio.sleep(config.metrics_interval)

    async def _handle_command(self, command: dict):
        """Handle a command received from backend."""
        cmd_type = command.get("command")
        command_id = command.get("command_id", "unknown")
        payload = command.get("payload", {})

        logger.info(f"Received command: {cmd_type} (id: {command_id})")

        try:
            if cmd_type == "get_metrics":
                # Return current metrics
                if self._metrics_collector:
                    metrics = self._metrics_collector.collect()
                    if metrics:
                        await self._backend_client.send_command_result(
                            command_id,
                            success=True,
                            result={"metrics": metrics.to_dict()}
                        )
                        return

                await self._backend_client.send_command_result(
                    command_id,
                    success=False,
                    error="Metrics collector not available"
                )

            elif cmd_type == "run_command":
                # Run a shell command (with restrictions)
                shell_cmd = payload.get("command")
                if not shell_cmd:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error="No command provided"
                    )
                    return

                # Security: Only allow certain safe commands
                allowed_prefixes = [
                    "systemctl status",
                    "df ",
                    "free ",
                    "uptime",
                    "uname",
                    "hostname",
                    "cat /proc/",
                    "ls ",
                    "ps aux",
                    "top -bn1",
                    "docker ps",
                    "docker stats --no-stream",
                ]

                allowed = any(shell_cmd.strip().startswith(p) for p in allowed_prefixes)
                if not allowed:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error="Command not in allowed list"
                    )
                    return

                # Run the command
                try:
                    result = subprocess.run(
                        shell_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    await self._backend_client.send_command_result(
                        command_id,
                        success=result.returncode == 0,
                        result={
                            "stdout": result.stdout[:4096],
                            "stderr": result.stderr[:1024],
                            "return_code": result.returncode
                        }
                    )
                except subprocess.TimeoutExpired:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error="Command timed out"
                    )

            elif cmd_type == "restart_service":
                # Restart a systemd service (requires permissions)
                service = payload.get("service")
                if not service:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error="No service name provided"
                    )
                    return

                # Security: Only allow specific services
                allowed_services = payload.get("allowed_services", [])
                if service not in allowed_services and not service.startswith("sara-"):
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error=f"Service '{service}' not in allowed list"
                    )
                    return

                try:
                    result = subprocess.run(
                        ["systemctl", "restart", service],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    await self._backend_client.send_command_result(
                        command_id,
                        success=result.returncode == 0,
                        result={"output": result.stdout + result.stderr}
                    )
                except Exception as e:
                    await self._backend_client.send_command_result(
                        command_id,
                        success=False,
                        error=str(e)
                    )

            elif cmd_type == "ping":
                # Simple ping/pong
                await self._backend_client.send_command_result(
                    command_id,
                    success=True,
                    result={"pong": True}
                )

            else:
                logger.warning(f"Unknown command type: {cmd_type}")
                await self._backend_client.send_command_result(
                    command_id,
                    success=False,
                    error=f"Unknown command: {cmd_type}"
                )

        except Exception as e:
            logger.exception(f"Command execution error: {e}")
            await self._backend_client.send_command_result(
                command_id,
                success=False,
                error=str(e)
            )


async def main():
    """Main entry point."""
    service = HeadlessAgentService()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(service.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        await service.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
