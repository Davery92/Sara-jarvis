"""
Device Commands API Routes
WebSocket and HTTP endpoints for cross-device command routing
"""
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import verify_token
from app.core.deps import get_current_user
from app.models.user import User
from app.db.session import get_db
from app.services.command_router import command_router, CommandType, CommandMessage
from app.services.machine_registry import machine_registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


# Request/Response models

class CommandRequest(BaseModel):
    """Request to send a command to a device"""
    command: str  # CommandType value
    payload: dict = {}
    target_device_id: Optional[str] = None  # None = active device


class CommandResponse(BaseModel):
    """Response from command send"""
    success: bool
    message: str
    target_device_id: Optional[str] = None


class DeviceInfo(BaseModel):
    """Device information"""
    device_id: str
    hostname: Optional[str]
    platform: Optional[str]
    is_online: bool
    is_connected: bool  # Has active WebSocket
    activity_level: str
    last_activity_at: Optional[datetime]


class HeartbeatRequest(BaseModel):
    """Device heartbeat with activity metrics"""
    activity_level: str  # idle, low, medium, high
    keyboard_events: int = 0
    mouse_events: int = 0
    mouse_distance: float = 0.0
    active_window: Optional[str] = None
    active_app: Optional[str] = None
    idle_seconds: float = 0.0


class HeartbeatResponse(BaseModel):
    """Response to heartbeat"""
    acknowledged: bool
    server_time: datetime
    screenshot_interval: int
    commands_pending: int = 0


# WebSocket endpoint for device connections

@router.websocket("/ws/{device_id}")
async def device_websocket(
    websocket: WebSocket,
    device_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for desktop agents to connect and receive commands.

    Protocol:
    1. Connect with device_id in path and JWT token as query param
    2. Send heartbeats with activity metrics
    3. Receive commands as JSON messages

    Message types from server:
    - command: A command to execute (open_url, show_note, etc.)
    - config: Configuration updates

    Message types from client:
    - heartbeat: Activity metrics
    - command_result: Result of executed command
    """
    # Verify token
    try:
        payload = verify_token(token)
        if not payload:
            await websocket.close(code=4001, reason="Invalid token")
            return
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token payload")
            return
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        await websocket.close(code=4001, reason="Token verification failed")
        return

    await websocket.accept()
    logger.info(f"Device WebSocket connected: {device_id} for user {user_id}")

    # Register the device connection
    connection = await command_router.register_device(websocket, device_id, user_id)

    # Get database session for machine registry
    db = next(get_db())

    try:
        # Send initial config
        machine = await machine_registry_service.get_machine_by_device_id(db, device_id)
        if machine:
            await websocket.send_json({
                "type": "config",
                "screenshot_interval": machine.screenshot_interval_seconds,
                "screenshot_enabled": machine.screenshot_enabled
            })

        # Listen for messages from device
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "heartbeat":
                # Update machine registry with activity metrics
                activity_level = data.get("activity_level", "idle")
                keyboard_events = data.get("keyboard_events", 0)
                mouse_events = data.get("mouse_events", 0)
                active_window = data.get("active_window")
                active_app = data.get("active_app")

                await machine_registry_service.update_heartbeat(
                    db=db,
                    device_id=device_id,
                    activity_level=activity_level,
                    keyboard_events=keyboard_events,
                    mouse_events=mouse_events,
                    active_window=active_window,
                    active_app=active_app
                )

                # Acknowledge heartbeat
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "server_time": datetime.utcnow().isoformat()
                })

            elif msg_type == "command_result":
                # Log command result
                command_id = data.get("command_id")
                success = data.get("success", False)
                error = data.get("error")
                logger.info(
                    f"Command {command_id} result from {device_id}: "
                    f"success={success}, error={error}"
                )

            elif msg_type == "screenshot_ready":
                # Device has a screenshot ready to upload
                logger.info(f"Screenshot ready from {device_id}")

            else:
                logger.warning(f"Unknown message type from {device_id}: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"Device WebSocket disconnected: {device_id}")
    except Exception as e:
        logger.exception(f"Device WebSocket error for {device_id}: {e}")
    finally:
        await command_router.unregister_device(device_id)
        # Mark machine as offline
        await machine_registry_service.mark_offline(db, device_id)
        db.close()


# HTTP endpoints for sending commands

@router.post("/command", response_model=CommandResponse)
async def send_command(
    request: CommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a command to a device.

    If target_device_id is not specified, sends to the most active device.

    Command types:
    - open_url: Open a URL in browser. Payload: {"url": "..."}
    - show_note: Show a note overlay. Payload: {"note_id": "...", "title": "...", "content": "..."}
    - show_timer: Show a timer overlay. Payload: {"timer_id": "...", "label": "...", "remaining_seconds": N}
    - take_screenshot: Request a screenshot. Payload: {"analyze": bool, "analyze_prompt": "..."}
    - speak: Speak text via TTS. Payload: {"text": "..."}
    - show_notification: Show a notification. Payload: {"title": "...", "message": "..."}
    """
    user_id = current_user.id

    try:
        command_type = CommandType(request.command)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command type: {request.command}"
        )

    command = CommandMessage(
        command_type=command_type,
        payload=request.payload,
        target_device_id=request.target_device_id
    )

    success = await command_router.send_command(db, user_id, command)

    if success:
        target = request.target_device_id or "active device"
        return CommandResponse(
            success=True,
            message=f"Command {request.command} sent to {target}",
            target_device_id=request.target_device_id
        )
    else:
        return CommandResponse(
            success=False,
            message="No connected device available",
            target_device_id=None
        )


@router.post("/open-url")
async def open_url(
    url: str,
    target_device_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Open a URL on the active (or specified) device."""
    success = await command_router.open_url(
        db, current_user.id, url
    )
    return {"success": success, "url": url}


@router.post("/show-note")
async def show_note(
    note_id: str,
    title: str,
    content: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Show a note overlay on the active device."""
    success = await command_router.show_note(
        db, current_user.id, note_id, title, content
    )
    return {"success": success, "note_id": note_id}


@router.post("/take-screenshot")
async def take_screenshot(
    analyze: bool = False,
    analyze_prompt: Optional[str] = None,
    target_device_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Request a screenshot from a device."""
    success = await command_router.take_screenshot(
        db, current_user.id, analyze, analyze_prompt, target_device_id
    )
    return {"success": success}


@router.get("/connected")
async def get_connected_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[DeviceInfo]:
    """
    Get all devices for the current user with their connection status.
    """
    user_id = current_user.id

    # Get all registered machines
    machines = await machine_registry_service.get_user_machines(
        db, user_id, include_offline=True
    )

    # Get currently connected device IDs
    connected_ids = set(command_router.get_connected_devices(user_id))

    devices = []
    for machine in machines:
        devices.append(DeviceInfo(
            device_id=machine.device_id,
            hostname=machine.hostname,
            platform=machine.platform,
            is_online=machine.is_online,
            is_connected=machine.device_id in connected_ids,
            activity_level=machine.activity_level or "idle",
            last_activity_at=machine.last_activity_at
        ))

    return devices


@router.get("/active")
async def get_active_device(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the currently active device for the user.
    This is the device that would receive commands.
    """
    user_id = current_user.id
    device_id = await command_router.get_active_device_id(db, user_id)

    if device_id:
        machine = await machine_registry_service.get_machine_by_device_id(db, device_id)
        if machine:
            return {
                "device_id": device_id,
                "hostname": machine.hostname,
                "platform": machine.platform,
                "activity_level": machine.activity_level
            }

    return {"device_id": None, "message": "No active device"}


@router.post("/register")
async def register_device(
    device_id: str,
    hostname: str,
    platform: str,
    os_version: Optional[str] = None,
    agent_version: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Register a new device or update existing registration.
    Called by desktop agents on startup.
    """
    user_id = current_user.id

    machine = await machine_registry_service.register_machine(
        db=db,
        user_id=user_id,
        device_id=device_id,
        hostname=hostname,
        platform=platform,
        os_version=os_version,
        capabilities=["screenshot", "wake_word", "commands"],
        agent_version=agent_version
    )

    return {
        "success": True,
        "machine_id": machine.id,
        "device_id": machine.device_id,
        "config": {
            "screenshot_enabled": machine.screenshot_enabled,
            "screenshot_interval_seconds": machine.screenshot_interval_seconds
        }
    }


@router.post("/heartbeat")
async def device_heartbeat(
    device_id: str,
    request: HeartbeatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Receive heartbeat from a device (HTTP fallback if WebSocket not used).
    """
    machine = await machine_registry_service.update_heartbeat(
        db, device_id, request.activity_level
    )

    if not machine:
        raise HTTPException(status_code=404, detail="Device not registered")

    return HeartbeatResponse(
        acknowledged=True,
        server_time=datetime.utcnow(),
        screenshot_interval=machine.screenshot_interval_seconds
    )
