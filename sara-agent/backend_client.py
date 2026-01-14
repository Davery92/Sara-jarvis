"""
Backend WebSocket Client for Sara Headless Agent

Maintains WebSocket connection to the Sara backend for:
- Device registration
- Heartbeat/metrics reporting
- Receiving and executing commands
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from config import AgentConfig

logger = logging.getLogger(__name__)


class BackendClient:
    """
    WebSocket client for backend communication.

    Handles connection, reconnection, and message routing.
    """

    def __init__(
        self,
        config: "AgentConfig",
        on_command: Optional[Callable] = None
    ):
        self.config = config
        self.on_command = on_command

        self._ws = None
        self._connected = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    async def connect(self):
        """Connect to the backend WebSocket."""
        if not self.config.auth_token:
            logger.error("No auth token configured, cannot connect to backend")
            # Wait and retry in case token gets configured later
            while not self.config.auth_token:
                logger.info("Waiting for auth token...")
                await asyncio.sleep(30)
                self.config.load_settings()

        while True:
            try:
                await self._connect_websocket()
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")

            if not self._connected:
                logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
            else:
                self._reconnect_delay = 1.0

    async def _connect_websocket(self):
        """Establish WebSocket connection."""
        import websockets

        ws_url = f"{self.config.backend_ws_url}/{self.config.device_id}?token={self.config.auth_token}"

        logger.info(f"Connecting to backend: {self.config.backend_ws_url}")

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                self._ws = websocket
                self._connected = True
                logger.info("Connected to backend WebSocket")

                # Register device
                await self._register_device()

                # Listen for messages
                async for message in websocket:
                    await self._handle_message(message)

        except Exception as e:
            self._connected = False
            self._ws = None
            raise

    async def _register_device(self):
        """Register this device with the backend."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.config.backend_url}/api/devices/register",
                    params={
                        "device_id": self.config.device_id,
                        "hostname": self.config.hostname,
                        "platform": self.config.platform_name,
                        "os_version": self.config.os_version,
                        "agent_version": "1.0.0",
                        "agent_type": self.config.agent_type,
                    },
                    headers={"Authorization": f"Bearer {self.config.auth_token}"},
                    timeout=10.0
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Device registered: {result.get('device_id')}")

                # Update config with server settings
                server_config = result.get("config", {})
                if "heartbeat_interval" in server_config:
                    self.config.heartbeat_interval = server_config["heartbeat_interval"]
                if "metrics_interval" in server_config:
                    self.config.metrics_interval = server_config["metrics_interval"]

        except Exception as e:
            logger.error(f"Device registration failed: {e}")

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "command":
                # Forward to command handler
                if self.on_command:
                    if asyncio.iscoroutinefunction(self.on_command):
                        await self.on_command(data)
                    else:
                        self.on_command(data)

            elif msg_type == "config":
                # Update configuration
                if "heartbeat_interval" in data:
                    self.config.heartbeat_interval = data["heartbeat_interval"]
                    logger.info(f"Heartbeat interval updated: {data['heartbeat_interval']}s")
                if "metrics_interval" in data:
                    self.config.metrics_interval = data["metrics_interval"]
                    logger.info(f"Metrics interval updated: {data['metrics_interval']}s")

            elif msg_type == "heartbeat_ack":
                # Heartbeat acknowledged
                pass

            elif msg_type == "ping":
                # Respond to ping
                await self.send_message({"type": "pong"})

            else:
                logger.debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON message: {message[:100]}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")

    async def disconnect(self):
        """Disconnect from the backend."""
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._connected = False

    async def send_message(self, message: dict):
        """Send a message to the backend."""
        if not self._ws or not self._connected:
            return False

        try:
            await self._ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            self._connected = False
            return False

    async def send_heartbeat(self, metrics: Optional[dict] = None):
        """Send heartbeat with optional metrics."""
        if not self._ws or not self._connected:
            return

        try:
            message = {
                "type": "heartbeat",
                "agent_type": self.config.agent_type,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            if metrics:
                message["metrics"] = metrics

            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Heartbeat send error: {e}")
            self._connected = False

    async def send_metrics(self, metrics: dict):
        """Send full metrics report."""
        if not self._ws or not self._connected:
            return

        try:
            message = {
                "type": "metrics",
                "metrics": metrics,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self._ws.send(json.dumps(message))
            logger.debug("Metrics sent successfully")

        except Exception as e:
            logger.error(f"Metrics send error: {e}")
            self._connected = False

    async def send_command_result(
        self,
        command_id: str,
        success: bool,
        result: Optional[dict] = None,
        error: Optional[str] = None
    ):
        """Report the result of a command execution."""
        if not self._ws or not self._connected:
            return

        try:
            message = {
                "type": "command_result",
                "command_id": command_id,
                "success": success,
                "result": result,
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Command result send error: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if connected to backend."""
        return self._connected
