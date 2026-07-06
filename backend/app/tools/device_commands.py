"""
Device Commands Tools

Tools for Sara to send commands to connected desktop agents.
Enables cross-device actions like showing notifications, opening URLs, etc.
"""
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from app.services.command_router import command_router, CommandMessage, CommandType
from app.services.machine_registry import machine_registry_service
from sqlalchemy.orm import Session


class DeviceRecordVoiceNoteTool(BaseTool):
    """Start (or stop-and-file) a voice note recording, routed by presence."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "device_record_voice_note"

    @property
    def description(self) -> str:
        return (
            "Record a voice note. Decides where to capture based on presence: "
            "if David is home and the Jetson is healthy, it captures there; "
            "otherwise it records on his active desktop. Use when the user says "
            "'record a note', 'take a voice note', or similar."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            from app.services.device_presence import resolve as resolve_presence
            presence = await resolve_presence(db, user_id)

            # Jetson dispatch needs a backend->Jetson control channel that
            # doesn't exist yet (the Jetson only has an outbound event/job
            # channel today — see Workstream B). Once that lands, this
            # branch routes there instead of falling through to desktop.
            at_home_with_jetson = presence.location_context == "home" and presence.active_device_id == "jetson"
            if at_home_with_jetson:
                return ToolResult(
                    success=False,
                    message=(
                        "David is home and the Jetson is healthy, but the backend->Jetson "
                        "record dispatch isn't wired yet — recording on the desktop instead."
                    ),
                    data={"presence": presence.__dict__},
                )

            success = await command_router.record_voice_note(db, user_id)
            if success:
                return ToolResult(success=True, message="Recording a voice note on your desktop.")
            return ToolResult(success=False, message="No connected device available to record on.")
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to start voice note: {e}")
        finally:
            db.close()


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
        return "Open the full note editor overlay on a connected desktop device. IMPORTANT: When the user asks to 'show a note on my PC/desktop/computer', first use notes_search to find the note (to get its note_id), then use THIS tool to display it. Pass the device_name the user mentioned (e.g., 'PC', 'laptop', 'MacBook') - the tool will find the matching device."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The id of an existing note to open in the full editor (from notes_search)."
                },
                "title": {
                    "type": "string",
                    "description": "Fallback: a title for a throwaway note when there's no note_id (e.g. an ad-hoc quote of text)."
                },
                "content": {
                    "type": "string",
                    "description": "Fallback: content for a throwaway note when there's no note_id."
                },
                "device_name": {
                    "type": "string",
                    "description": "The device name the user mentioned (e.g., 'PC', 'laptop', 'MacBook', 'desktop'). Will match against friendly_name or hostname."
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open the note editor overlay on a device"""
        note_id = kwargs.get("note_id")
        title = kwargs.get("title")
        content = kwargs.get("content")
        device_name = kwargs.get("device_name")

        if not note_id and not (title and content):
            return ToolResult(success=False, message="Either note_id, or both title and content, are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            target_device_id = await _resolve_target_device_id(db, user_id, device_name)

            if note_id:
                payload = {"note_id": note_id}
            else:
                import uuid
                payload = {"note_id": f"quick-{uuid.uuid4().hex[:8]}", "title": title, "content": content}

            success = await command_router.open_overlay(
                db, user_id, "note", payload,
                target_device_id=target_device_id
            )

            if success:
                target_desc = f"'{device_name}'" if device_name else "active device"
                return ToolResult(
                    success=True,
                    message=f"Opening note on {target_desc}",
                    data={"note_id": payload["note_id"], "device": device_name}
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


class DeviceOpenOverlayTool(BaseTool):
    """Generic tool for opening any overlay kind on a connected desktop."""

    @property
    def name(self) -> str:
        return "device_open_overlay"

    @property
    def description(self) -> str:
        return (
            "Open an overlay window on a connected desktop device: 'note', "
            "'blank-note', 'nutrition', 'brief', 'report', 'calendar', "
            "'tasks', 'timers', 'inbox', or 'recipes'. Use this for surfaces "
            "not covered by a more specific device tool (device_show_note "
            "covers 'note'). Use when the user asks to pull up/open/show one "
            "of these on their PC/desktop/computer."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Overlay kind: nutrition, brief, report, calendar, tasks, timers, inbox, recipes, blank-note, note.",
                    "enum": ["nutrition", "brief", "report", "calendar", "tasks", "timers", "inbox", "recipes", "blank-note", "note"],
                },
                "payload": {
                    "type": "object",
                    "description": "Optional overlay-specific payload, e.g. {\"report_type\": \"research_brief\", \"latest\": true} for 'report'."
                },
                "device_name": {
                    "type": "string",
                    "description": "Optional device the user mentioned. Omit for the most active device."
                }
            },
            "required": ["kind"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        kind = kwargs.get("kind")
        payload = kwargs.get("payload") or {}
        device_name = kwargs.get("device_name")

        if not kind:
            return ToolResult(success=False, message="kind is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            target_device_id = await _resolve_target_device_id(db, user_id, device_name)
            success = await command_router.open_overlay(
                db, user_id, kind, payload, target_device_id=target_device_id
            )
            if success:
                target_desc = f"'{device_name}'" if device_name else "active device"
                return ToolResult(
                    success=True,
                    message=f"Opening {kind} on {target_desc}",
                    data={"kind": kind, "device": device_name},
                )
            return ToolResult(
                success=False,
                message=f"No connected device found matching '{device_name}'." if device_name else "No connected device available.",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to open overlay: {e}")
        finally:
            db.close()


class DeviceTakeScreenshotTool(BaseTool):
    """Tool for requesting screenshots from devices, with in-turn vision analysis."""

    @property
    def name(self) -> str:
        return "device_take_screenshot"

    @property
    def description(self) -> str:
        return (
            "See what's on the user's screen right now — captures a screenshot from a "
            "connected desktop and answers a question about it in this same turn. Use this "
            "for 'what am I looking at?', 'what's on my screen', 'what does this error say', "
            "etc. Always pass `question` with what the user actually wants to know."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What to look for / answer about the screenshot. Defaults to a general description if omitted."
                },
                "device_id": {
                    "type": "string",
                    "description": "Optional: specific device ID"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Request a screenshot and wait for its in-turn vision analysis."""
        device_id = kwargs.get("device_id")
        question = kwargs.get("question")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            command = CommandMessage(
                command_type=CommandType.TAKE_SCREENSHOT,
                payload={"analyze": True, "analyze_prompt": question, "return_result": True},
                target_device_id=device_id,
            )
            outcome = await command_router.send_command_and_wait(db, user_id, command, timeout=15.0)

            if not outcome:
                return ToolResult(
                    success=False,
                    message="No connected device available, or it didn't respond in time.",
                )
            if not outcome.get("success"):
                return ToolResult(
                    success=False,
                    message=f"Screenshot failed: {outcome.get('error') or 'unknown error'}",
                )

            analysis = (outcome.get("result") or {}).get("analysis")
            if not analysis:
                return ToolResult(
                    success=False,
                    message="Screenshot captured but vision analysis didn't return anything.",
                )
            return ToolResult(success=True, message=analysis, data=outcome.get("result"))

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


async def _resolve_target_device_id(
    db: Session, user_id: str, device_name: Optional[str]
) -> Optional[str]:
    """Match a user-provided device name to a registered machine."""
    if not device_name:
        return None
    machines = await machine_registry_service.get_user_machines(
        db, user_id, include_offline=False
    )
    device_name_lower = device_name.lower()
    for m in machines:
        friendly = (m.friendly_name or "").lower()
        hostname = (m.hostname or "").lower()
        platform = (m.platform or "").lower()
        if (device_name_lower in friendly or
            device_name_lower in hostname or
            (device_name_lower in ['pc', 'windows'] and platform == 'windows') or
            (device_name_lower in ['mac', 'macbook'] and platform == 'darwin')):
            return m.device_id
    return None


class DeviceWriteClipboardTool(BaseTool):
    """Write text to the clipboard on a connected desktop."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "device_write_clipboard"

    @property
    def description(self) -> str:
        return (
            "Write text to the clipboard on a connected desktop device, so the user "
            "can paste it. Use when the user asks you to put something on their "
            "clipboard, copy something for them, or prepare text for pasting."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to place on the clipboard."
                },
                "device_name": {
                    "type": "string",
                    "description": "Optional device the user mentioned (e.g., 'PC', 'laptop'). Omit for the most active device."
                }
            },
            "required": ["text"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        text = kwargs.get("text")
        if text is None:
            return ToolResult(success=False, message="text is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            target_device_id = await _resolve_target_device_id(
                db, user_id, kwargs.get("device_name")
            )
            success = await command_router.write_clipboard(
                db, user_id, text, target_device_id=target_device_id
            )
            if success:
                preview = text if len(text) <= 40 else text[:37] + "…"
                return ToolResult(
                    success=True,
                    message=f"Copied to clipboard: {preview}",
                    data={"chars": len(text)},
                )
            return ToolResult(
                success=False,
                message="No connected device available.",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to write clipboard: {e}")
        finally:
            db.close()


class DeviceFocusWindowTool(BaseTool):
    """Bring a window matching a title substring to the foreground."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "device_focus_window"

    @property
    def description(self) -> str:
        return (
            "Bring a window to the foreground on a connected desktop by matching "
            "part of its title (case-insensitive). Use when the user asks to "
            "switch to, focus, or pull up a window/app by name."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title_match": {
                    "type": "string",
                    "description": "Substring of the target window title (e.g., 'Outlook', 'Cursor', 'Slack')."
                },
                "device_name": {
                    "type": "string",
                    "description": "Optional device the user mentioned. Omit for the most active device."
                }
            },
            "required": ["title_match"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        title_match = kwargs.get("title_match")
        if not title_match:
            return ToolResult(success=False, message="title_match is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            target_device_id = await _resolve_target_device_id(
                db, user_id, kwargs.get("device_name")
            )
            success = await command_router.focus_window(
                db, user_id, title_match, target_device_id=target_device_id
            )
            if success:
                return ToolResult(
                    success=True,
                    message=f"Focusing window matching '{title_match}'",
                    data={"title_match": title_match},
                )
            return ToolResult(
                success=False,
                message="No connected device available.",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to focus window: {e}")
        finally:
            db.close()


class DeviceTypeIntoWindowTool(BaseTool):
    """Focus a window matching a title substring AND type text into it, atomically."""

    requires_user_origin = True

    @property
    def name(self) -> str:
        return "device_type_into_window"

    @property
    def description(self) -> str:
        return (
            "Type `text` into a specific window identified by `title_match` "
            "(case-insensitive substring of the window's title) on a connected "
            "desktop. The sidecar focuses the window and types in a single atomic "
            "step — there is no separate focus tool because that would create a "
            "focus race with the chat UI. Use this whenever the user asks you "
            "to type something into a named app or window (e.g., 'type X in "
            "Notepad', 'paste this into Outlook'). If the user only said to "
            "'type' without naming where, ask them which window."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title_match": {
                    "type": "string",
                    "description": "Substring of the target window's title (e.g., 'Notepad', 'Outlook', 'Cursor')."
                },
                "text": {
                    "type": "string",
                    "description": "The text to type. Newlines become Enter keypresses."
                },
                "device_name": {
                    "type": "string",
                    "description": "Optional device the user mentioned. Omit for the most active device."
                }
            },
            "required": ["title_match", "text"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        title_match = kwargs.get("title_match")
        text = kwargs.get("text")
        if not title_match:
            return ToolResult(success=False, message="title_match is required")
        if text is None or text == "":
            return ToolResult(success=False, message="text is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            target_device_id = await _resolve_target_device_id(
                db, user_id, kwargs.get("device_name")
            )
            success = await command_router.type_into_window(
                db, user_id, title_match, text, target_device_id=target_device_id
            )
            if success:
                preview = text if len(text) <= 40 else text[:37] + "…"
                return ToolResult(
                    success=True,
                    message=f"Typing into '{title_match}': {preview}",
                    data={"chars": len(text), "title_match": title_match},
                )
            return ToolResult(
                success=False,
                message="No connected device available.",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to type into window: {e}")
        finally:
            db.close()


# Export all tools
DEVICE_TOOLS = [
    DeviceListTool(),
    DeviceSendNotificationTool(),
    DeviceOpenUrlTool(),
    DeviceShowNoteTool(),
    DeviceOpenOverlayTool(),
    DeviceTakeScreenshotTool(),
    DeviceOpenWorkspaceTool(),
    DeviceWriteClipboardTool(),
    DeviceFocusWindowTool(),
    DeviceTypeIntoWindowTool(),
    DeviceRecordVoiceNoteTool(),
]
