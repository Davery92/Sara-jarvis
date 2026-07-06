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
import random
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
        on_command: Optional[Callable] = None,
        on_event: Optional[Callable] = None,
        on_config_update: Optional[Callable] = None,
        on_auth_invalid: Optional[Callable] = None
    ):
        self.config = config
        self.on_command = on_command
        # Generic backend->device realtime events (hud_state, voice_state,
        # attention_count, timer_update — A3). Called as on_event(event, data).
        self.on_event = on_event
        # Fired whenever a `config` message arrives (initial connect or a
        # live Settings > Privacy push) — called as on_config_update(data).
        self.on_config_update = on_config_update
        # Fired when the backend rejects our token (WS close code 4001) —
        # retrying with the same token would just loop forever, so this
        # stops the reconnect loop and asks the UI to prompt for re-login.
        self.on_auth_invalid = on_auth_invalid

        self._ws = None
        self._connected = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._invalid_token = False

    async def connect(self):
        """Connect to the backend WebSocket."""
        if not self.config.auth_token:
            logger.error("No auth token configured, cannot connect to backend")
            return

        while not self._invalid_token:
            try:
                await self._connect_websocket()
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")

            if self._invalid_token:
                logger.error("Backend rejected auth token (4001); stopping reconnect loop")
                if self.on_auth_invalid:
                    result = self.on_auth_invalid()
                    if asyncio.iscoroutine(result):
                        await result
                break

            if not self._connected:
                # Full jitter: spreads reconnect storms out (e.g. after a
                # backend restart, every sidecar doesn't retry in lockstep).
                delay = self._reconnect_delay * (0.7 + random.random() * 0.6)
                logger.info(f"Reconnecting in {delay:.1f}s...")
                await asyncio.sleep(delay)
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

        except websockets.exceptions.ConnectionClosedError as e:
            self._connected = False
            self._ws = None
            if e.code == 4001:
                self._invalid_token = True
            else:
                raise
        except Exception as e:
            self._connected = False
            self._ws = None
            raise

    # Capabilities this sidecar build actually implements. Checked by
    # command_router before sending commands that require them (A3) so an
    # older/lighter sidecar build fails a capability check instead of
    # silently dropping the command.
    CAPABILITIES = ["screenshot", "commands", "actuators"]

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
                        "capabilities": self.CAPABILITIES,
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
                if "screenshot_enabled" in data:
                    self.config.screenshot_enabled = data["screenshot_enabled"]
                    logger.info(f"Screenshot enabled updated: {data['screenshot_enabled']}")
                if self.on_config_update:
                    if asyncio.iscoroutinefunction(self.on_config_update):
                        await self.on_config_update(data)
                    else:
                        self.on_config_update(data)

            elif msg_type == "heartbeat_ack":
                # Heartbeat acknowledged
                pass

            elif msg_type == "event":
                # Generic backend->device realtime event: hud_state,
                # voice_state, attention_count, timer_update (A3).
                if self.on_event:
                    event_name = data.get("event")
                    event_data = data.get("data", {})
                    if asyncio.iscoroutinefunction(self.on_event):
                        await self.on_event(event_name, event_data)
                    else:
                        self.on_event(event_name, event_data)

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
                "media_state": activity.get("media_state", False),
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

    async def send_focus_span(self, span: dict) -> None:
        """Send a completed focus span to the backend."""
        if not self._ws or not self._connected:
            return
        try:
            message = {"type": "focus_span", **span,
                       "timestamp": datetime.utcnow().isoformat()}
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"focus_span send error: {e}")
            self._connected = False

    async def send_activity_state(self, state: dict) -> None:
        """Send a desktop activity state transition to the backend."""
        if not self._ws or not self._connected:
            return
        try:
            message = {"type": "activity_state", **state,
                       "timestamp": datetime.utcnow().isoformat()}
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"activity_state send error: {e}")
            self._connected = False

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
                "timestamp": datetime.utcnow().isoformat()
            }
            await self._ws.send(json.dumps(message))

        except Exception as e:
            logger.error(f"Command result send error: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if connected to backend."""
        return self._connected
