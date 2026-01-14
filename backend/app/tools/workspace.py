"""
Workspace Control Tools

Tools for Sara to control the workbench-canvas workspace.
These tools return workspace_command data that the workbench-canvas frontend
interprets to open windows, arrange the workspace, and manage state.

NOTE: These tools are different from the canvas tools (canvas.py) which control
the side panel in the main webapp. Workspace tools control the full workbench-canvas
application (the infinite canvas with multiple windows).
"""

from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.db.session import get_db
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class WorkspaceOpenWindowTool(BaseTool):
    """Tool for opening a window in the workspace canvas"""

    @property
    def name(self) -> str:
        return "workspace_open_window"

    @property
    def description(self) -> str:
        return """Open a new window in the workspace canvas. Use this to open different types of windows
like notes browser, chat, fitness tracker, calendar, or other available window types.
The window will appear in the user's workspace canvas."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_type": {
                    "type": "string",
                    "enum": ["notes", "chat", "fitness", "calendar", "tasks", "intelligence", "settings"],
                    "description": "Type of window to open: 'notes' for notes browser, 'chat' for another chat window, 'fitness' for fitness tracking, 'calendar' for calendar view, 'tasks' for task list, 'intelligence' for intelligence reports, 'settings' for settings"
                },
                "title": {
                    "type": "string",
                    "description": "Optional custom title for the window"
                },
                "data": {
                    "type": "object",
                    "description": "Optional data to pass to the window (varies by window type)"
                }
            },
            "required": ["window_type"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open a window in the workspace"""

        window_type = kwargs.get("window_type")
        title = kwargs.get("title")
        data = kwargs.get("data", {})

        if not window_type:
            return ToolResult(
                success=False,
                message="window_type is required"
            )

        # Default titles for window types
        default_titles = {
            "notes": "Notes",
            "chat": "Chat",
            "fitness": "Fitness",
            "calendar": "Calendar",
            "tasks": "Tasks",
            "intelligence": "Intelligence",
            "settings": "Settings"
        }

        window_title = title or default_titles.get(window_type, window_type.title())

        return ToolResult(
            success=True,
            data={
                "workspace_command": "open_window",
                "window_type": window_type,
                "title": window_title,
                "data": data
            },
            message=f"Opening {window_title} window in workspace"
        )


class WorkspaceOpenNoteTool(BaseTool):
    """Tool for opening a specific note in the workspace"""

    @property
    def name(self) -> str:
        return "workspace_open_note"

    @property
    def description(self) -> str:
        return """Open a specific note in a dedicated note editor window in the workspace.
You can specify either the note ID or search by title. The note will open in its own
window for focused editing."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to open"
                },
                "note_title": {
                    "type": "string",
                    "description": "The title of the note to search for (used if note_id not provided)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open a specific note in the workspace"""

        note_id = kwargs.get("note_id")
        note_title = kwargs.get("note_title")

        if not note_id and not note_title:
            return ToolResult(
                success=False,
                message="Either note_id or note_title is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            note = None

            if note_id:
                # Direct lookup by ID
                note = db.query(Note).filter(
                    Note.id == note_id,
                    Note.user_id == user_id
                ).first()

            if not note and note_title:
                # Search by title (case-insensitive)
                note = db.query(Note).filter(
                    Note.user_id == user_id,
                    Note.title.ilike(f"%{note_title}%")
                ).order_by(Note.updated_at.desc()).first()

            if not note:
                return ToolResult(
                    success=False,
                    message=f"Note not found: {note_id or note_title}"
                )

            # Return workspace command with note data
            return ToolResult(
                success=True,
                data={
                    "workspace_command": "open_window",
                    "window_type": "note_editor",
                    "title": note.title or "Untitled Note",
                    "data": {
                        "note_id": str(note.id),
                        "title": note.title or "",
                        "content": note.content,
                        "folder_id": note.folder_id
                    }
                },
                message=f"Opening note: {note.title or 'Untitled'}",
                citations=[f"note:{note.id}"]
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to open note: {str(e)}"
            )
        finally:
            db.close()


class WorkspaceCloseWindowTool(BaseTool):
    """Tool for closing a window in the workspace"""

    @property
    def name(self) -> str:
        return "workspace_close_window"

    @property
    def description(self) -> str:
        return """Close a window in the workspace. You can specify the window by its ID
or by its title. If no identifier is provided, this will request closing the currently
focused window."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_id": {
                    "type": "string",
                    "description": "The ID of the window to close"
                },
                "window_title": {
                    "type": "string",
                    "description": "The title of the window to close (matches partial title)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Close a window in the workspace"""

        window_id = kwargs.get("window_id")
        window_title = kwargs.get("window_title")

        return ToolResult(
            success=True,
            data={
                "workspace_command": "close_window",
                "window_id": window_id,
                "window_title": window_title
            },
            message=f"Closing window: {window_title or window_id or 'current'}"
        )


class WorkspaceSaveStateTool(BaseTool):
    """Tool for saving the current workspace state"""

    @property
    def name(self) -> str:
        return "workspace_save_state"

    @property
    def description(self) -> str:
        return """Request the workspace to save its current state (window positions, sizes,
and canvas view). The saved state can be restored when reopening the workspace or
on a different device."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Request workspace state save"""

        return ToolResult(
            success=True,
            data={
                "workspace_command": "save_state"
            },
            message="Requesting workspace state save"
        )


class WorkspaceArrangeTool(BaseTool):
    """Tool for arranging windows in the workspace"""

    @property
    def name(self) -> str:
        return "workspace_arrange"

    @property
    def description(self) -> str:
        return """Arrange the windows in the workspace using a predefined layout.
Options include tiling windows in a grid, cascading them, stacking them,
or centering them on the canvas."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "arrangement": {
                    "type": "string",
                    "enum": ["tile", "cascade", "stack", "center"],
                    "description": "Arrangement type: 'tile' for grid layout, 'cascade' for overlapping diagonal, 'stack' for vertical stack, 'center' for centering all windows"
                }
            },
            "required": ["arrangement"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Arrange workspace windows"""

        arrangement = kwargs.get("arrangement", "tile")

        return ToolResult(
            success=True,
            data={
                "workspace_command": "arrange_windows",
                "arrangement": arrangement
            },
            message=f"Arranging windows: {arrangement}"
        )


class WorkspaceFocusWindowTool(BaseTool):
    """Tool for focusing a specific window in the workspace"""

    @property
    def name(self) -> str:
        return "workspace_focus_window"

    @property
    def description(self) -> str:
        return """Bring a specific window to the front and focus it. You can specify
the window by its ID or title."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_id": {
                    "type": "string",
                    "description": "The ID of the window to focus"
                },
                "window_title": {
                    "type": "string",
                    "description": "The title of the window to focus (matches partial title)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Focus a window in the workspace"""

        window_id = kwargs.get("window_id")
        window_title = kwargs.get("window_title")

        return ToolResult(
            success=True,
            data={
                "workspace_command": "focus_window",
                "window_id": window_id,
                "window_title": window_title
            },
            message=f"Focusing window: {window_title or window_id or 'none specified'}"
        )


# List of all workspace tools for easy import
WORKSPACE_TOOLS = [
    WorkspaceOpenWindowTool(),
    WorkspaceOpenNoteTool(),
    WorkspaceCloseWindowTool(),
    WorkspaceSaveStateTool(),
    WorkspaceArrangeTool(),
    WorkspaceFocusWindowTool(),
]
