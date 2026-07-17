"""
Command Router Service
Routes commands to the appropriate active device via WebSocket
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy.orm import Session
from fastapi import WebSocket

from app.services.machine_registry import machine_registry_service

logger = logging.getLogger(__name__)


class CommandType(str, Enum):
    """Types of commands that can be sent to devices"""
    OPEN_URL = "open_url"
    SHOW_NOTE = "show_note"
    SHOW_TIMER = "show_timer"
    TAKE_SCREENSHOT = "take_screenshot"
    SPEAK = "speak"
    SHOW_NOTIFICATION = "show_notification"
    START_LISTENING = "start_listening"
    OPEN_WORKSPACE = "open_workspace"  # Open the workbench-canvas in browser
    # Desktop actuators — user-initiated only (enforced by BaseTool.requires_user_origin)
    WRITE_CLIPBOARD = "write_clipboard"
    FOCUS_WINDOW = "focus_window"
    TYPE_INTO_WINDOW = "type_into_window"
    # Overlay/HUD/voice-note plane (Desktop Jarvis Overhaul, Workstream A3)
    OPEN_OVERLAY = "open_overlay"
    RECORD_VOICE_NOTE = "record_voice_note"
    CANCEL_SPEECH = "cancel_speech"
    HUD_STATE = "hud_state"  # backend-pushed orb state (informational, no ack expected)


# Capability required to honor each command type. Checked against
# Machine.capabilities before sending; missing capability -> send_command
# returns False so callers can fall back (e.g. push notification instead of
# a desktop toast). Command types absent from this map have no requirement.
COMMAND_CAPABILITY_REQUIREMENTS: Dict["CommandType", str] = {
    CommandType.SPEAK: "tts",
    CommandType.RECORD_VOICE_NOTE: "mic",
    CommandType.OPEN_OVERLAY: "overlays",
    CommandType.TAKE_SCREENSHOT: "screenshot",
    CommandType.WRITE_CLIPBOARD: "actuators",
    CommandType.FOCUS_WINDOW: "actuators",
    CommandType.TYPE_INTO_WINDOW: "actuators",
}


@dataclass
class DeviceConnection:
    """Represents an active WebSocket connection to a device"""
    device_id: str
    user_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CommandMessage:
    """A command to be sent to a device"""
    command_type: CommandType
    payload: Dict[str, Any]
    source_device_id: Optional[str] = None  # Which device initiated the command
    target_device_id: Optional[str] = None  # Specific target, or None for active device
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    required_capability: Optional[str] = None  # Overrides COMMAND_CAPABILITY_REQUIREMENTS lookup


class CommandRouterService:
    """
    Manages device connections and routes commands to active devices.

    Devices connect via WebSocket and register themselves.
    Commands can be sent to specific devices or routed to the most active one.
    """

    def __init__(self):
        # device_id -> DeviceConnection
        self._connections: Dict[str, DeviceConnection] = {}
        # user_id -> list of device_ids
        self._user_devices: Dict[str, list] = {}
        # Callbacks for command handling
        self._command_handlers: Dict[CommandType, Callable] = {}
        # command_id -> Future, resolved when a command_result arrives for it.
        # Used by send_command_and_wait (A3: ack-with-results).
        self._pending_results: Dict[str, "asyncio.Future"] = {}

    async def register_device(
        self,
        websocket: WebSocket,
        device_id: str,
        user_id: str
    ) -> DeviceConnection:
        """
        Register a device's WebSocket connection.
        Called when a device connects to the command WebSocket.
        """
        connection = DeviceConnection(
            device_id=device_id,
            user_id=user_id,
            websocket=websocket
        )

        # Store the connection
        self._connections[device_id] = connection

        # Track user's devices
        if user_id not in self._user_devices:
            self._user_devices[user_id] = []
        if device_id not in self._user_devices[user_id]:
            self._user_devices[user_id].append(device_id)

        logger.info(f"Device {device_id} registered for user {user_id}")
        return connection

    async def unregister_device(self, device_id: str):
        """
        Unregister a device when it disconnects.
        """
        if device_id in self._connections:
            connection = self._connections[device_id]
            user_id = connection.user_id

            del self._connections[device_id]

            # Remove from user's device list
            if user_id in self._user_devices:
                if device_id in self._user_devices[user_id]:
                    self._user_devices[user_id].remove(device_id)
                if not self._user_devices[user_id]:
                    del self._user_devices[user_id]

            logger.info(f"Device {device_id} unregistered")

    def get_connected_devices(self, user_id: str) -> list:
        """Get list of connected device IDs for a user."""
        return self._user_devices.get(user_id, [])

    def is_device_connected(self, device_id: str) -> bool:
        """Check if a specific device is connected."""
        return device_id in self._connections

    async def get_active_device_id(
        self,
        db: Session,
        user_id: str
    ) -> Optional[str]:
        """
        Get the most active connected device for a user.

        Delegates the "who's active" question to the unified device_presence
        resolver (A7), but keeps this class's own connected-check — a
        presence answer naming a device that isn't actually WS-connected
        here is useless for command delivery, so we still verify before
        trusting it and fall back to the original machine-registry logic.
        """
        try:
            from app.services.device_presence import resolve as resolve_presence
            presence = await resolve_presence(db, user_id)
            if presence.active_device_id and presence.active_device_id in self._connections:
                return presence.active_device_id
        except Exception as e:
            logger.warning(f"device_presence resolution failed, falling back: {e}")

        # Get the most active machine from the registry
        machine = await machine_registry_service.get_most_active_machine(db, user_id)

        if machine and machine.device_id in self._connections:
            return machine.device_id

        # Fallback: return any connected device
        connected = self.get_connected_devices(user_id)
        return connected[0] if connected else None

    async def _has_capability(
        self, db: Session, device_id: str, capability: str
    ) -> bool:
        """Check whether a device has advertised a given capability.

        Machines registered before capability reporting existed have an
        empty/partial list — treat that as "unknown" (allow) rather than
        blocking every command for devices that haven't reported yet.
        """
        machine = await machine_registry_service.get_machine_by_device_id(db, device_id)
        if machine is None:
            return True
        capabilities = machine.capabilities or []
        if not capabilities:
            return True
        return capability in capabilities

    async def send_command(
        self,
        db: Session,
        user_id: str,
        command: CommandMessage
    ) -> bool:
        """
        Send a command to a device.

        If target_device_id is specified, sends to that device.
        Otherwise, sends to the most active device.

        Returns True if the command was sent successfully.
        """
        target_device_id = command.target_device_id

        if not target_device_id:
            target_device_id = await self.get_active_device_id(db, user_id)

        if not target_device_id:
            logger.warning(f"No active device found for user {user_id}")
            return False

        if target_device_id not in self._connections:
            logger.warning(f"Device {target_device_id} not connected")
            return False

        required_capability = (
            command.required_capability
            or COMMAND_CAPABILITY_REQUIREMENTS.get(command.command_type)
        )
        if required_capability and not await self._has_capability(
            db, target_device_id, required_capability
        ):
            logger.info(
                f"Device {target_device_id} lacks capability '{required_capability}' "
                f"for command {command.command_type.value}; not sending"
            )
            return False

        connection = self._connections[target_device_id]

        try:
            message = {
                "type": "command",
                "command": command.command_type.value,
                "command_id": command.command_id,
                "payload": command.payload,
                "source_device": command.source_device_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            await connection.websocket.send_json(message)
            connection.last_message_at = datetime.now(timezone.utc)

            logger.info(
                f"Command {command.command_type.value} ({command.command_id}) "
                f"sent to device {target_device_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send command to {target_device_id}: {e}")
            # Device probably disconnected
            await self.unregister_device(target_device_id)
            return False

    async def send_command_and_wait(
        self,
        db: Session,
        user_id: str,
        command: CommandMessage,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """Send a command and wait for its command_result to come back.

        Returns the result payload (`{"success": bool, "result": ..., "error": ...}`)
        or None if the command couldn't be sent or timed out.
        """
        loop = asyncio.get_event_loop()
        future: "asyncio.Future" = loop.create_future()
        self._pending_results[command.command_id] = future

        try:
            sent = await self.send_command(db, user_id, command)
            if not sent:
                return None

            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Timed out waiting for result of command {command.command_id} "
                    f"({command.command_type.value})"
                )
                return None
        finally:
            self._pending_results.pop(command.command_id, None)

    def resolve_command_result(self, command_id: str, result: Dict[str, Any]) -> bool:
        """Resolve a pending send_command_and_wait() future with its result.

        Called from the device WebSocket handler when a `command_result`
        message arrives. Returns True if a waiter was actually resolved.
        """
        future = self._pending_results.get(command_id)
        if future is None or future.done():
            return False
        future.set_result(result)
        return True

    async def broadcast_to_user(
        self,
        user_id: str,
        message: Dict[str, Any]
    ) -> int:
        """
        Broadcast a message to all connected devices for a user.
        Returns the number of devices that received the message.
        """
        device_ids = self.get_connected_devices(user_id)
        sent_count = 0

        for device_id in device_ids:
            if device_id in self._connections:
                try:
                    await self._connections[device_id].websocket.send_json(message)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Failed to broadcast to {device_id}: {e}")
                    await self.unregister_device(device_id)

        return sent_count

    # Convenience methods for common commands

    async def open_url(
        self,
        db: Session,
        user_id: str,
        url: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None
    ) -> bool:
        """Open a URL on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.OPEN_URL,
            payload={"url": url},
            source_device_id=source_device_id,
            target_device_id=target_device_id
        )
        return await self.send_command(db, user_id, command)

    async def show_note(
        self,
        db: Session,
        user_id: str,
        note_id: str,
        note_title: str,
        note_content: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None
    ) -> bool:
        """Show a note on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.SHOW_NOTE,
            payload={
                "note_id": note_id,
                "title": note_title,
                "content": note_content
            },
            source_device_id=source_device_id,
            target_device_id=target_device_id
        )
        return await self.send_command(db, user_id, command)

    async def show_timer(
        self,
        db: Session,
        user_id: str,
        timer_id: str,
        label: str,
        remaining_seconds: int,
        source_device_id: Optional[str] = None
    ) -> bool:
        """Show a timer on the active device."""
        command = CommandMessage(
            command_type=CommandType.SHOW_TIMER,
            payload={
                "timer_id": timer_id,
                "label": label,
                "remaining_seconds": remaining_seconds
            },
            source_device_id=source_device_id
        )
        return await self.send_command(db, user_id, command)

    async def take_screenshot(
        self,
        db: Session,
        user_id: str,
        analyze: bool = False,
        analyze_prompt: Optional[str] = None,
        target_device_id: Optional[str] = None
    ) -> bool:
        """Request a screenshot from a device."""
        command = CommandMessage(
            command_type=CommandType.TAKE_SCREENSHOT,
            payload={
                "analyze": analyze,
                "analyze_prompt": analyze_prompt
            },
            target_device_id=target_device_id
        )
        return await self.send_command(db, user_id, command)

    async def show_notification(
        self,
        db: Session,
        user_id: str,
        title: str,
        message: str,
        source_device_id: Optional[str] = None
    ) -> bool:
        """Show a notification on the active device."""
        command = CommandMessage(
            command_type=CommandType.SHOW_NOTIFICATION,
            payload={
                "title": title,
                "message": message
            },
            source_device_id=source_device_id
        )
        return await self.send_command(db, user_id, command)

    async def speak(
        self,
        db: Session,
        user_id: str,
        text: str,
        source_device_id: Optional[str] = None
    ) -> bool:
        """Have the active device speak text via TTS."""
        command = CommandMessage(
            command_type=CommandType.SPEAK,
            payload={"text": text},
            source_device_id=source_device_id
        )
        return await self.send_command(db, user_id, command)

    async def start_listening(
        self,
        db: Session,
        user_id: str,
        source_device_id: Optional[str] = None
    ) -> bool:
        """Tell the active device to start listening (wake word triggered)."""
        command = CommandMessage(
            command_type=CommandType.START_LISTENING,
            payload={},
            source_device_id=source_device_id
        )
        return await self.send_command(db, user_id, command)

    async def open_workspace(
        self,
        db: Session,
        user_id: str,
        workspace_url: str = "https://canvas.avery.cloud",
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None
    ) -> bool:
        """Open the workbench-canvas workspace on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.OPEN_WORKSPACE,
            payload={"url": workspace_url},
            source_device_id=source_device_id,
            target_device_id=target_device_id
        )
        return await self.send_command(db, user_id, command)

    # ── Overlay / voice-note / speech-control plane (A3) ─────────────────────

    async def open_overlay(
        self,
        db: Session,
        user_id: str,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Open an overlay window of the given kind on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.OPEN_OVERLAY,
            payload={"kind": kind, "payload": payload or {}},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)

    async def record_voice_note(
        self,
        db: Session,
        user_id: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Ask a device (desktop sidecar or Jetson) to start recording a voice note."""
        command = CommandMessage(
            command_type=CommandType.RECORD_VOICE_NOTE,
            payload={},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)

    async def cancel_speech(
        self,
        db: Session,
        user_id: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Stop any in-progress TTS playback on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.CANCEL_SPEECH,
            payload={},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)

    async def push_event(
        self,
        user_id: str,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        target_device_id: Optional[str] = None,
    ) -> int:
        """Push a fire-and-forget realtime event to one or all connected devices.

        Used for hud_state / voice_state / attention_count / timer_update —
        informational updates that don't need a command_result ack. Returns
        the number of devices the event was delivered to.
        """
        message = {
            "type": "event",
            "event": event,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if target_device_id:
            connection = self._connections.get(target_device_id)
            if not connection:
                return 0
            try:
                await connection.websocket.send_json(message)
                connection.last_message_at = datetime.now(timezone.utc)
                return 1
            except Exception as e:
                logger.error(f"Failed to push event to {target_device_id}: {e}")
                await self.unregister_device(target_device_id)
                return 0

        return await self.broadcast_to_user(user_id, message)

    async def send_config_update(
        self,
        device_id: str,
        screenshot_enabled: Optional[bool] = None,
        screenshot_interval_seconds: Optional[int] = None,
    ) -> bool:
        """Push a live `config` message to a connected device so a Settings >
        Privacy toggle takes effect immediately, without a sidecar reconnect."""
        connection = self._connections.get(device_id)
        if not connection:
            return False

        message: Dict[str, Any] = {"type": "config"}
        if screenshot_enabled is not None:
            message["screenshot_enabled"] = screenshot_enabled
        if screenshot_interval_seconds is not None:
            message["screenshot_interval"] = screenshot_interval_seconds
        if len(message) == 1:
            return False

        try:
            await connection.websocket.send_json(message)
            connection.last_message_at = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error(f"Failed to push config update to {device_id}: {e}")
            await self.unregister_device(device_id)
            return False

    # ── Desktop actuators (user-originated only) ────────────────────────────

    async def write_clipboard(
        self,
        db: Session,
        user_id: str,
        text: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Write text to the clipboard on the specified or active device."""
        command = CommandMessage(
            command_type=CommandType.WRITE_CLIPBOARD,
            payload={"text": text},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)

    async def focus_window(
        self,
        db: Session,
        user_id: str,
        title_match: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Bring a window with a title containing `title_match` to the foreground."""
        command = CommandMessage(
            command_type=CommandType.FOCUS_WINDOW,
            payload={"title_match": title_match},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)

    async def type_into_window(
        self,
        db: Session,
        user_id: str,
        title_match: str,
        text: str,
        source_device_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
    ) -> bool:
        """Atomically focus a window matching `title_match` and type `text` into it.

        Bundles focus + type into a single sidecar op so the LLM never gets a
        chance to insert a turn between the two — eliminates the Windows focus
        race that the previous separate focus_window/type_text pair was vulnerable to.
        """
        command = CommandMessage(
            command_type=CommandType.TYPE_INTO_WINDOW,
            payload={"title_match": title_match, "text": text},
            source_device_id=source_device_id,
            target_device_id=target_device_id,
        )
        return await self.send_command(db, user_id, command)


# Global service instance
command_router = CommandRouterService()
