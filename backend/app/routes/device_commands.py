"""
Device Commands API Routes
WebSocket and HTTP endpoints for cross-device command routing
"""
import logging
from datetime import datetime
from typing import Optional, List
import secrets
import uuid

from app.core.timezone import now as local_now
from fastapi import APIRouter, Body, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

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
    friendly_name: Optional[str] = None
    is_online: bool
    is_connected: bool  # Has active WebSocket
    activity_level: str
    last_activity_at: Optional[datetime]

    @property
    def status(self) -> str:
        if self.is_connected:
            return "connected"
        if self.is_online:
            return "online"
        return "offline"


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
                    "server_time": local_now().isoformat()
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
        info = DeviceInfo(
            device_id=machine.device_id,
            hostname=machine.hostname,
            platform=machine.platform,
            friendly_name=getattr(machine, 'friendly_name', None),
            is_online=machine.is_online,
            is_connected=machine.device_id in connected_ids,
            activity_level=machine.activity_level or "idle",
            last_activity_at=machine.last_activity_at,
        )
        devices.append(info)

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
    request: Request,
    payload: Optional[dict] = Body(default=None),
    device_id: Optional[str] = None,
    hostname: Optional[str] = None,
    platform: Optional[str] = None,
    os_version: Optional[str] = None,
    agent_version: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Unified device registration endpoint.

    Supports both:
    - Desktop/headless agents (query params): device_id, hostname, platform
    - Pi dashboard (JSON body): device_name/device_type -> returns device_token
    """
    body = payload or {}
    user_id = str(current_user.id)

    resolved_device_id = device_id or body.get("device_id")
    resolved_hostname = hostname or body.get("hostname")
    resolved_platform = platform or body.get("platform")

    # Desktop/headless agent flow
    if resolved_device_id and resolved_hostname and resolved_platform:
        machine = await machine_registry_service.register_machine(
            db=db,
            user_id=user_id,
            device_id=resolved_device_id,
            hostname=resolved_hostname,
            platform=resolved_platform,
            os_version=os_version,
            capabilities=["screenshot", "wake_word", "commands"],
            agent_version=agent_version,
        )

        return {
            "success": True,
            "machine_id": machine.id,
            "device_id": machine.device_id,
            "config": {
                "screenshot_enabled": machine.screenshot_enabled,
                "screenshot_interval_seconds": machine.screenshot_interval_seconds,
                # Used by headless agent if provided by server
                "heartbeat_interval": 30,
                "metrics_interval": 60,
            },
        }

    # Pi dashboard flow (requires JSON body contract)
    pi_payload = bool(body.get("device_name") or body.get("device_type"))
    if not pi_payload:
        raise HTTPException(
            status_code=422,
            detail="Provide either device_id/hostname/platform or device_name/device_type",
        )

    device_name = (body.get("device_name") or request.headers.get("X-Device-Name") or "Unknown Device").strip()
    device_type = str(body.get("device_type") or "pi_dashboard").strip() or "pi_dashboard"

    # Reuse existing token for same user+device_name to avoid token churn.
    existing = db.execute(
        text(
            """
            SELECT id, device_token
            FROM device_registration
            WHERE user_id = :user_id
              AND device_name = :device_name
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"user_id": user_id, "device_name": device_name},
    ).fetchone()

    if existing:
        db.execute(
            text(
                """
                UPDATE device_registration
                SET last_seen = NOW(), device_type = :device_type
                WHERE id = :id
                """
            ),
            {"id": existing.id, "device_type": device_type},
        )
        db.commit()
        return {
            "device_id": existing.id,
            "device_token": existing.device_token,
            "message": "Device already registered. Returning existing token.",
        }

    device_token = secrets.token_urlsafe(32)
    token_id = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO device_registration (id, user_id, device_name, device_token, device_type, last_seen, created_at)
            VALUES (:id, :user_id, :device_name, :device_token, :device_type, NOW(), NOW())
            """
        ),
        {
            "id": token_id,
            "user_id": user_id,
            "device_name": device_name,
            "device_token": device_token,
            "device_type": device_type,
        },
    )
    db.commit()

    return {
        "device_id": token_id,
        "device_token": device_token,
        "message": "Device registered. Store this token securely.",
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
        server_time=local_now(),
        screenshot_interval=machine.screenshot_interval_seconds
    )


# =================== Device Management Endpoints ===================


class UpdateDeviceNameRequest(BaseModel):
    """Request to update device friendly name"""
    friendly_name: str


class DeviceListItem(BaseModel):
    """Device info for list display"""
    device_id: str
    friendly_name: Optional[str]
    hostname: Optional[str]
    platform: Optional[str]
    is_online: bool
    activity_level: str
    last_activity_at: Optional[datetime]
    last_heartbeat_at: Optional[datetime]


@router.get("/list")
async def list_user_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all devices for the current user with online status and friendly names.
    Used by the webapp settings page for device management.
    """
    devices = await machine_registry_service.get_user_machines(
        db, str(current_user.id), include_offline=True
    )

    return {
        "devices": [
            {
                "device_id": d.device_id,
                "friendly_name": d.friendly_name,
                "hostname": d.hostname,
                "platform": d.platform,
                "is_online": d.is_online,
                "activity_level": d.activity_level or "idle",
                "last_activity_at": d.last_activity_at.isoformat() if d.last_activity_at else None,
                "last_heartbeat_at": d.last_heartbeat_at.isoformat() if d.last_heartbeat_at else None,
            }
            for d in devices
        ]
    }


@router.patch("/{device_id}/name")
async def update_device_name(
    device_id: str,
    body: UpdateDeviceNameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the friendly name of a device.
    """
    # Verify the device belongs to this user
    machine = await machine_registry_service.get_machine_by_device_id(db, device_id)
    if not machine or machine.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="Device not found")

    updated = await machine_registry_service.update_friendly_name(
        db, device_id, body.friendly_name
    )

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update device name")

    return {
        "success": True,
        "device_id": device_id,
        "friendly_name": body.friendly_name
    }


@router.delete("/{device_id}")
async def remove_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove a device from the registry.
    """
    from sqlalchemy import delete, and_
    from app.models.machine import Machine

    # Delete only if it belongs to this user
    stmt = delete(Machine).where(
        and_(
            Machine.device_id == device_id,
            Machine.user_id == str(current_user.id)
        )
    )
    result = db.execute(stmt)
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Device not found")

    return {"success": True, "device_id": device_id}
