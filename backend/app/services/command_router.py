"""
Command Router Service
Routes commands to the appropriate active device via WebSocket
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
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


@dataclass
class DeviceConnection:
    """Represents an active WebSocket connection to a device"""
    device_id: str
    user_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_message_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CommandMessage:
    """A command to be sent to a device"""
    command_type: CommandType
    payload: Dict[str, Any]
    source_device_id: Optional[str] = None  # Which device initiated the command
    target_device_id: Optional[str] = None  # Specific target, or None for active device


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
        Uses the machine registry to determine activity level.
        """
        # Get the most active machine from the registry
        machine = await machine_registry_service.get_most_active_machine(db, user_id)

        if machine and machine.device_id in self._connections:
            return machine.device_id

        # Fallback: return any connected device
        connected = self.get_connected_devices(user_id)
        return connected[0] if connected else None

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

        connection = self._connections[target_device_id]

        try:
            message = {
                "type": "command",
                "command": command.command_type.value,
                "payload": command.payload,
                "source_device": command.source_device_id,
                "timestamp": datetime.utcnow().isoformat()
            }

            await connection.websocket.send_json(message)
            connection.last_message_at = datetime.utcnow()

            logger.info(
                f"Command {command.command_type.value} sent to device {target_device_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send command to {target_device_id}: {e}")
            # Device probably disconnected
            await self.unregister_device(target_device_id)
            return False

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


# Global service instance
command_router = CommandRouterService()
