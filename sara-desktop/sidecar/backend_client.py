"""
Backend WebSocket Client

Maintains WebSocket connection to the Sara backend for:
- Device registration
- Heartbeat/activity reporting
- Receiving commands
- Screenshot uploads
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional, Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from config import SidecarConfig

logger = logging.getLogger(__name__)


class BackendClient:
    """
    WebSocket client for backend communication.

    Handles connection, reconnection, and message routing.
    """

    def __init__(
        self,
        config: "SidecarConfig",
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
            return

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
                        "agent_version": "1.0.0"
                    },
                    headers={"Authorization": f"Bearer {self.config.auth_token}"},
                    timeout=10.0
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"Device registered: {result.get('device_id')}")

                # Update config with server settings
                server_config = result.get("config", {})
                if "screenshot_interval_seconds" in server_config:
                    self.config.screenshot_interval = server_config["screenshot_interval_seconds"]

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
                if "screenshot_interval" in data:
                    self.config.screenshot_interval = data["screenshot_interval"]
                    logger.info(f"Screenshot interval updated: {data['screenshot_interval']}s")

            elif msg_type == "heartbeat_ack":
                # Heartbeat acknowledged
                pass

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

    async def send_heartbeat(self, activity: dict):
        """Send heartbeat with activity metrics."""
        if not self._ws or not self._connected:
            return

        try:
            message = {
                "type": "heartbeat",
                "activity_level": activity.get("activity_level", "idle"),
                "keyboard_events": activity.get("keyboard_events", 0),
                "mouse_events": activity.get("mouse_events", 0),
                "active_window": activity.get("active_window"),
                "active_app": activity.get("active_app"),
                "timestamp": datetime.utcnow().isoformat()
            }
            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Heartbeat send error: {e}")
            self._connected = False

    async def send_event(self, event_type: str, data: dict):
        """Send an event to the backend."""
        if not self._ws or not self._connected:
            return

        try:
            message = {
                "type": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Event send error: {e}")

    async def upload_screenshot(
        self,
        image_data: bytes,
        window_title: Optional[str] = None,
        app_name: Optional[str] = None,
        analyze: bool = False,
        analyze_prompt: Optional[str] = None
    ) -> dict:
        """Upload a screenshot to the backend."""
        if not self.config.auth_token:
            raise Exception("No auth token configured")

        try:
            async with httpx.AsyncClient() as client:
                files = {"file": ("screenshot.jpg", image_data, "image/jpeg")}
                data = {
                    "device_id": self.config.device_id,
                    "analyze": str(analyze).lower()
                }

                if window_title:
                    data["window_title"] = window_title
                if app_name:
                    data["app_name"] = app_name
                if analyze_prompt:
                    data["analyze_prompt"] = analyze_prompt

                response = await client.post(
                    f"{self.config.backend_url}/api/vision/screenshot",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {self.config.auth_token}"},
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error(f"Screenshot upload error: {e}")
            raise

    async def send_command_result(
        self,
        command_id: str,
        success: bool,
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
                "error": error,
                "timestamp": datetime.utcnow().isoformat()
            }
            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Command result send error: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if connected to backend."""
        return self._connected
