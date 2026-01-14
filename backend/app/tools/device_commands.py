"""
Device Commands Tools

Tools for Sara to send commands to connected desktop agents.
Enables cross-device actions like showing notifications, opening URLs, etc.
"""
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from app.services.command_router import command_router
from app.services.machine_registry import machine_registry_service
from sqlalchemy.orm import Session


class DeviceListTool(BaseTool):
    """Tool for listing connected devices"""

    @property
    def name(self) -> str:
        return "device_list"

    @property
    def description(self) -> str:
        return "List all devices registered to the user, showing which are currently online. Use this to see available devices before sending commands."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List user's devices"""
        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            machines = await machine_registry_service.get_user_machines(db, user_id, include_offline=True)

            if not machines:
                return ToolResult(
                    success=True,
                    message="No devices registered. The user needs to install and run the Sara desktop agent.",
                    data={"devices": []}
                )

            devices = []
            for m in machines:
                # Check if device is connected to command router
                is_connected = m.device_id in command_router._connections
                devices.append({
                    "device_id": m.device_id,
                    "name": m.friendly_name or m.hostname,
                    "hostname": m.hostname,
                    "platform": m.platform,
                    "is_online": m.is_online,
                    "is_connected": is_connected,
                    "activity_level": m.activity_level,
                    "last_seen": m.last_heartbeat_at.isoformat() if m.last_heartbeat_at else None
                })

            online_count = sum(1 for d in devices if d["is_connected"])

            return ToolResult(
                success=True,
                message=f"Found {len(devices)} device(s), {online_count} currently connected.",
                data={"devices": devices}
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list devices: {str(e)}")
        finally:
            db.close()


class DeviceSendNotificationTool(BaseTool):
    """Tool for sending notifications to devices"""

    @property
    def name(self) -> str:
        return "device_send_notification"

    @property
    def description(self) -> str:
        return "Send a notification to a connected device. If no device_id is specified, sends to the most active device. Use device_list first to see available devices."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The notification title"
                },
                "message": {
                    "type": "string",
                    "description": "The notification message/body"
                },
                "device_id": {
                    "type": "string",
                    "description": "Optional: specific device ID to send to. If not provided, sends to the most active device."
                }
            },
            "required": ["title", "message"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Send notification to device"""
        title = kwargs.get("title")
        message = kwargs.get("message")
        device_id = kwargs.get("device_id")

        if not title or not message:
            return ToolResult(success=False, message="Title and message are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            success = await command_router.show_notification(
                db, user_id, title, message
            )

            if success:
                return ToolResult(
                    success=True,
                    message=f"Notification sent: '{title}'",
                    data={"title": title, "message": message}
                )
            else:
                return ToolResult(
                    success=False,
                    message="No connected device available. The user's desktop agent may be offline."
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to send notification: {str(e)}")
        finally:
            db.close()


class DeviceOpenUrlTool(BaseTool):
    """Tool for opening URLs on devices"""

    @property
    def name(self) -> str:
        return "device_open_url"

    @property
    def description(self) -> str:
        return "Open a URL in the default browser on a connected desktop device. Use this when the user says 'open X on my PC/desktop/computer'. Pass the device_name the user mentioned."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to open"
                },
                "device_name": {
                    "type": "string",
                    "description": "The device name the user mentioned (e.g., 'PC', 'laptop', 'MacBook'). Will match against friendly_name or hostname."
                }
            },
            "required": ["url"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open URL on device"""
        url = kwargs.get("url")
        device_name = kwargs.get("device_name")

        if not url:
            return ToolResult(success=False, message="URL is required")

        # Ensure URL has protocol
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Look up device by friendly name or hostname if specified
            target_device_id = None
            if device_name:
                machines = await machine_registry_service.get_user_machines(db, user_id, include_offline=False)
                device_name_lower = device_name.lower()
                for m in machines:
                    friendly = (m.friendly_name or "").lower()
                    hostname = (m.hostname or "").lower()
                    platform = (m.platform or "").lower()
                    if (device_name_lower in friendly or
                        device_name_lower in hostname or
                        (device_name_lower in ['pc', 'windows'] and platform == 'windows') or
                        (device_name_lower in ['mac', 'macbook'] and platform == 'darwin')):
                        target_device_id = m.device_id
                        break

            success = await command_router.open_url(db, user_id, url, target_device_id=target_device_id)

            if success:
                target_desc = f"'{device_name}'" if device_name else "active device"
                return ToolResult(
                    success=True,
                    message=f"Opening {url} on {target_desc}",
                    data={"url": url, "device": device_name}
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"No connected device found matching '{device_name}'." if device_name else "No connected device available."
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to open URL: {str(e)}")
        finally:
            db.close()


class DeviceShowNoteTool(BaseTool):
    """Tool for showing notes on devices"""

    @property
    def name(self) -> str:
        return "device_show_note"

    @property
    def description(self) -> str:
        return "Display a note popup on a connected desktop device. IMPORTANT: When the user asks to 'show a note on my PC/desktop/computer', first use notes_search to find the note, then use THIS tool to display it. Pass the device_name the user mentioned (e.g., 'PC', 'laptop', 'MacBook') - the tool will find the matching device."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The note title"
                },
                "content": {
                    "type": "string",
                    "description": "The note content (supports markdown)"
                },
                "device_name": {
                    "type": "string",
                    "description": "The device name the user mentioned (e.g., 'PC', 'laptop', 'MacBook', 'desktop'). Will match against friendly_name or hostname."
                }
            },
            "required": ["title", "content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Show note on device"""
        title = kwargs.get("title")
        content = kwargs.get("content")
        device_name = kwargs.get("device_name")

        if not title or not content:
            return ToolResult(success=False, message="Title and content are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            import uuid
            note_id = f"quick-{uuid.uuid4().hex[:8]}"

            # Look up device by friendly name or hostname if specified
            target_device_id = None
            if device_name:
                machines = await machine_registry_service.get_user_machines(db, user_id, include_offline=False)
                device_name_lower = device_name.lower()
                for m in machines:
                    friendly = (m.friendly_name or "").lower()
                    hostname = (m.hostname or "").lower()
                    platform = (m.platform or "").lower()
                    # Match by friendly name, hostname, or platform keywords
                    if (device_name_lower in friendly or
                        device_name_lower in hostname or
                        (device_name_lower in ['pc', 'windows'] and platform == 'windows') or
                        (device_name_lower in ['mac', 'macbook'] and platform == 'darwin')):
                        target_device_id = m.device_id
                        break

            success = await command_router.show_note(
                db, user_id, note_id, title, content,
                target_device_id=target_device_id
            )

            if success:
                target_desc = f"'{device_name}'" if device_name else "active device"
                return ToolResult(
                    success=True,
                    message=f"Showing note '{title}' on {target_desc}",
                    data={"title": title, "note_id": note_id, "device": device_name}
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"No connected device found matching '{device_name}'." if device_name else "No connected device available."
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to show note: {str(e)}")
        finally:
            db.close()


class DeviceTakeScreenshotTool(BaseTool):
    """Tool for requesting screenshots from devices"""

    @property
    def name(self) -> str:
        return "device_take_screenshot"

    @property
    def description(self) -> str:
        return "Request an immediate screenshot from a connected device. The screenshot will be uploaded to the backend. Use this when you need to see what's on the user's screen."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Optional: specific device ID"
                },
                "analyze": {
                    "type": "boolean",
                    "description": "Whether to run vision analysis on the screenshot"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Request screenshot from device"""
        device_id = kwargs.get("device_id")
        analyze = kwargs.get("analyze", False)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            success = await command_router.take_screenshot(
                db, user_id, analyze=analyze, target_device_id=device_id
            )

            if success:
                return ToolResult(
                    success=True,
                    message="Screenshot requested. It will be uploaded shortly.",
                    data={"analyze": analyze}
                )
            else:
                return ToolResult(
                    success=False,
                    message="No connected device available."
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to request screenshot: {str(e)}")
        finally:
            db.close()


class DeviceOpenWorkspaceTool(BaseTool):
    """Tool for opening the workspace on a device"""

    @property
    def name(self) -> str:
        return "device_open_workspace"

    @property
    def description(self) -> str:
        return "Open the user's workspace (workbench-canvas) in a browser on a connected desktop device. Use this when the user says 'open my workspace on my PC/desktop/computer'. The workspace is the infinite canvas where the user can have multiple windows open."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "The device name the user mentioned (e.g., 'PC', 'laptop', 'MacBook'). Will match against friendly_name or hostname. If not specified, opens on the most active device."
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open workspace on device"""
        device_name = kwargs.get("device_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Look up device by friendly name or hostname if specified
            target_device_id = None
            if device_name:
                machines = await machine_registry_service.get_user_machines(db, user_id, include_offline=False)
                device_name_lower = device_name.lower()
                for m in machines:
                    friendly = (m.friendly_name or "").lower()
                    hostname = (m.hostname or "").lower()
                    platform = (m.platform or "").lower()
                    if (device_name_lower in friendly or
                        device_name_lower in hostname or
                        (device_name_lower in ['pc', 'windows'] and platform == 'windows') or
                        (device_name_lower in ['mac', 'macbook'] and platform == 'darwin')):
                        target_device_id = m.device_id
                        break

            success = await command_router.open_workspace(
                db, user_id, target_device_id=target_device_id
            )

            if success:
                target_desc = f"'{device_name}'" if device_name else "active device"
                return ToolResult(
                    success=True,
                    message=f"Opening workspace on {target_desc}",
                    data={"device": device_name}
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"No connected device found matching '{device_name}'." if device_name else "No connected device available."
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to open workspace: {str(e)}")
        finally:
            db.close()


# Export all tools
DEVICE_TOOLS = [
    DeviceListTool(),
    DeviceSendNotificationTool(),
    DeviceOpenUrlTool(),
    DeviceShowNoteTool(),
    DeviceTakeScreenshotTool(),
    DeviceOpenWorkspaceTool(),
]
