"""
Workspace Control Tools

Tools for Sara to control the workbench-canvas workspace.
These tools return workspace_command data that the workbench-canvas frontend
interprets to open windows, arrange the workspace, and manage state.

NOTE: These tools are different from the canvas tools (canvas.py) which control
the side panel in the main webapp. Workspace tools control the full workbench-canvas
application (the infinite canvas with multiple windows).
"""

from typing import Dict, Any, Optional, List
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.models.doc import Document
from app.models.email import Email, EmailAttachment
from app.models.workspace_state import WorkspaceState
from app.core.config import settings
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy import or_
import logging
import json
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

LAST_RESULTS_TTL_SECONDS = 60 * 30


def _get_redis():
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        return redis.from_url(url, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis not available for workspace result memory: {e}")
        return None


def _workspace_last_results_key(user_id: str) -> str:
    return f"workspace_last_results:{user_id}"


def _save_last_results(user_id: str, payload: Dict[str, Any]) -> None:
    try:
        redis_conn = _get_redis()
        if not redis_conn:
            return
        redis_conn.setex(_workspace_last_results_key(user_id), LAST_RESULTS_TTL_SECONDS, json.dumps(payload))
    except Exception as e:
        logger.warning(f"Failed to save workspace last results: {e}")


def _load_last_results(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        redis_conn = _get_redis()
        if not redis_conn:
            return None
        raw = redis_conn.get(_workspace_last_results_key(user_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Failed to load workspace last results: {e}")
        return None


def _score_text_match(query: str, *fields: Optional[str]) -> int:
    q = query.strip().lower()
    if not q:
        return 0
    terms = [t for t in q.split() if t]
    score = 0
    for idx, field in enumerate(fields):
        if not field:
            continue
        text = field.lower()
        weight = max(1, 4 - idx)
        if q in text:
            score += 7 * weight
        score += sum(1 for t in terms if t in text) * weight
    return score


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
                    "enum": ["notes", "chat", "fitness", "calendar", "tasks", "intelligence", "settings", "projects", "timers", "research", "email", "documents", "temerant"],
                    "description": "Type of window to open: 'notes' for notes browser, 'chat' for chat, 'fitness' for fitness tracking, 'calendar' for calendar, 'tasks' for task list, 'intelligence' for intelligence reports, 'settings' for settings, 'projects' for project tracker, 'timers' for timers, 'research' for web research, 'email' for inbox, 'documents' for uploaded docs, 'temerant' for the solo RPG habit system"
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
            "settings": "Settings",
            "projects": "Projects",
            "timers": "Timers",
            "research": "Research",
            "email": "Email",
            "documents": "Documents",
            "temerant": "Temerant",
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


class WorkspaceListWindowsTool(BaseTool):
    """Tool for listing all open windows in the workspace"""

    @property
    def name(self) -> str:
        return "workspace_list_windows"

    @property
    def description(self) -> str:
        return """List all currently open windows in the user's workspace canvas.
Returns window IDs, types, and titles so you can reference them for focus, close, or other operations.
Use this to see what windows the user has open before trying to focus or close a specific window."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_type": {
                    "type": "string",
                    "description": "Optional filter by window type (e.g., 'note', 'notes', 'chat', 'terminal')"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List open windows from workspace state"""
        window_type_filter = kwargs.get("window_type")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Get workspace state from database
            stmt = select(WorkspaceState).where(WorkspaceState.user_id == user_id)
            state = db.execute(stmt).scalar_one_or_none()

            if not state or not state.state_data:
                return ToolResult(
                    success=True,
                    data={"windows": [], "count": 0},
                    message="No workspace state found - workspace may not be open"
                )

            windows = state.state_data.get("windows", [])

            # Filter by type if specified
            if window_type_filter:
                filter_lower = window_type_filter.lower()
                windows = [w for w in windows if filter_lower in w.get("type", "").lower()]

            # Build summary for each window
            window_list = []
            for w in windows:
                window_info = {
                    "id": w.get("id"),
                    "type": w.get("type"),
                    "title": w.get("title"),
                }
                # Include note_id if it's a note window
                if w.get("data", {}).get("note_id"):
                    window_info["note_id"] = w["data"]["note_id"]
                if w.get("data", {}).get("note_title"):
                    window_info["note_title"] = w["data"]["note_title"]
                window_list.append(window_info)

            return ToolResult(
                success=True,
                data={
                    "windows": window_list,
                    "count": len(window_list)
                },
                message=f"Found {len(window_list)} open window(s) in workspace"
            )

        except Exception as e:
            logger.error(f"Error listing workspace windows: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to list windows: {str(e)}"
            )
        finally:
            db.close()


class WorkspaceFindAndOpenTool(BaseTool):
    """Find relevant emails/notes/documents and open workspace windows with results."""

    @property
    def name(self) -> str:
        return "workspace_find_and_open"

    @property
    def description(self) -> str:
        return """Search emails, notes, and documents using natural language intent, then open matching items in the workspace.
Use this when the user asks things like:
- "find emails about X"
- "find emails with attachments named Y"
- "find notes about X and open them"
- "find docs about X and pull them up"
This tool opens relevant windows automatically."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search phrase to look for in content, titles, subjects, senders, or previews."
                },
                "source": {
                    "type": "string",
                    "enum": ["emails", "notes", "documents", "all"],
                    "description": "Which data source(s) to search.",
                    "default": "all"
                },
                "attachment_name": {
                    "type": "string",
                    "description": "Optional attachment filename keyword for email searches."
                },
                "has_attachments": {
                    "type": "boolean",
                    "description": "If true, only include emails that have attachments.",
                    "default": False
                },
                "max_open": {
                    "type": "integer",
                    "description": "Maximum number of specific matching items to auto-open.",
                    "default": 3
                }
            },
            "required": ["query"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        source = (kwargs.get("source") or "all").lower()
        attachment_name = (kwargs.get("attachment_name") or "").strip()
        has_attachments = bool(kwargs.get("has_attachments", False))
        max_open = min(max(int(kwargs.get("max_open", 3)), 1), 6)

        if not query:
            return ToolResult(success=False, message="query is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            commands: List[Dict[str, Any]] = []
            summary_lines: List[str] = []
            memory_payload: Dict[str, Any] = {
                "query": query,
                "source": source,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "emails": [],
                "notes": [],
                "documents": [],
            }

            do_emails = source in ("emails", "all")
            do_notes = source in ("notes", "all")
            do_documents = source in ("documents", "all")

            if do_emails:
                email_query = db.query(Email).filter(Email.user_id == user_id)
                term = f"%{query}%"
                email_query = email_query.filter(
                    or_(
                        Email.subject.ilike(term),
                        Email.body_preview.ilike(term),
                        Email.sender_email.ilike(term),
                        Email.sender_name.ilike(term),
                    )
                )

                if has_attachments or attachment_name:
                    email_query = email_query.join(EmailAttachment, EmailAttachment.email_id == Email.id)
                if attachment_name:
                    email_query = email_query.filter(EmailAttachment.filename.ilike(f"%{attachment_name}%"))

                pool = email_query.distinct(Email.id).order_by(Email.id, Email.received_at.desc()).limit(30).all()
                ranked_emails = sorted(
                    pool,
                    key=lambda e: (
                        _score_text_match(query, e.subject, e.body_preview, e.sender_name, e.sender_email)
                        + (3 if (e.action_required or False) else 0)
                        + int((e.importance_score or 0) * 4)
                    ),
                    reverse=True
                )
                emails = ranked_emails[:max_open]
                summary_lines.append(f"emails: {len(emails)} match(es)")
                memory_payload["emails"] = [e.id for e in emails]

                # Open a filtered email workspace window
                commands.append({
                    "workspace_command": "open_window",
                    "window_type": "email",
                    "title": f"Email: {query}",
                    "data": {"initialQuery": query}
                })

                for email in emails:
                    commands.append({
                        "workspace_command": "open_window",
                        "window_type": "email",
                        "title": f"Email: {email.subject[:60] if email.subject else 'Untitled'}",
                        "data": {"emailId": email.id}
                    })

            if do_notes:
                term = f"%{query}%"
                note_pool = db.query(Note).filter(
                    Note.user_id == user_id,
                    or_(Note.title.ilike(term), Note.content.ilike(term)),
                ).order_by(Note.updated_at.desc()).limit(40).all()
                ranked_notes = sorted(
                    note_pool,
                    key=lambda n: _score_text_match(query, n.title, n.content),
                    reverse=True
                )
                notes = ranked_notes[:max_open]
                summary_lines.append(f"notes: {len(notes)} match(es)")
                memory_payload["notes"] = [str(n.id) for n in notes]

                # Open a search-oriented notes window first
                commands.append({
                    "workspace_command": "open_window",
                    "window_type": "notes",
                    "title": f"Notes: {query}",
                    "data": {"initialQuery": query}
                })

                for note in notes:
                    commands.append({
                        "workspace_command": "open_window",
                        "window_type": "note_editor",
                        "title": note.title or "Untitled Note",
                        "data": {
                            "note_id": str(note.id),
                            "title": note.title or "",
                            "content": note.content or "",
                            "folder_id": note.folder_id
                        }
                    })

            if do_documents:
                term = f"%{query}%"
                doc_pool = db.query(Document).filter(
                    Document.user_id == user_id,
                    or_(
                        Document.title.ilike(term),
                        Document.original_filename.ilike(term),
                        Document.content_text.ilike(term),
                    )
                ).order_by(Document.updated_at.desc()).limit(40).all()
                ranked_docs = sorted(
                    doc_pool,
                    key=lambda d: _score_text_match(query, d.title, d.original_filename, d.content_text),
                    reverse=True
                )
                documents = ranked_docs[:max_open]
                summary_lines.append(f"documents: {len(documents)} match(es)")
                memory_payload["documents"] = [
                    {"id": str(d.id), "filename": d.original_filename or d.filename or "document"}
                    for d in documents
                ]

                commands.append({
                    "workspace_command": "open_window",
                    "window_type": "documents",
                    "title": f"Documents: {query}",
                    "data": {"initialQuery": query}
                })

            if not commands:
                return ToolResult(
                    success=False,
                    message=f"No workspace actions generated for query '{query}'"
                )

            _save_last_results(user_id, memory_payload)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": commands[0].get("workspace_command"),
                    "workspace_commands": commands,
                    "query": query,
                },
                message=f"Opened workspace results for '{query}' ({', '.join(summary_lines)}). You can say 'open the second one' next."
            )
        except Exception as e:
            logger.error(f"workspace_find_and_open failed: {e}")
            return ToolResult(success=False, message=f"Failed to search and open workspace results: {str(e)}")
        finally:
            db.close()


class WorkspaceOpenFromLastResultsTool(BaseTool):
    """Open a result by index from the most recent workspace_find_and_open execution."""

    @property
    def name(self) -> str:
        return "workspace_open_from_last_results"

    @property
    def description(self) -> str:
        return """Open a specific result from the last workspace search by index.
Use for follow-ups like 'open the second one', 'open #3', or 'open first email from that search'."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["emails", "notes", "documents"],
                    "description": "Which result set to use from the last search. Optional if only one source was searched.",
                },
                "index": {
                    "type": "integer",
                    "description": "1-based position from the last search results.",
                    "default": 1,
                }
            },
            "required": ["index"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        source = (kwargs.get("source") or "").lower()
        index = int(kwargs.get("index", 1))
        if index < 1:
            return ToolResult(success=False, message="index must be >= 1")

        last = _load_last_results(user_id)
        if not last:
            return ToolResult(success=False, message="No recent workspace search results found. Run workspace_find_and_open first.")

        if source not in {"emails", "notes", "documents"}:
            preferred = (last.get("source") or "").lower()
            if preferred in {"emails", "notes", "documents"}:
                source = preferred
            else:
                for candidate in ("emails", "notes", "documents"):
                    if last.get(candidate):
                        source = candidate
                        break
        if source not in {"emails", "notes", "documents"}:
            return ToolResult(success=False, message="Could not infer source. Specify source as emails, notes, or documents.")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            if source == "emails":
                ids = last.get("emails") or []
                if index > len(ids):
                    return ToolResult(success=False, message=f"Only {len(ids)} email result(s) available.")
                email_id = ids[index - 1]
                email = db.query(Email).filter(Email.id == email_id, Email.user_id == user_id).first()
                if not email:
                    return ToolResult(success=False, message="Email result no longer exists.")
                return ToolResult(
                    success=True,
                    data={
                        "workspace_command": "open_window",
                        "window_type": "email",
                        "title": f"Email: {email.subject[:60] if email.subject else 'Untitled'}",
                        "data": {"emailId": email.id}
                    },
                    message=f"Opening email #{index} from last results."
                )

            if source == "notes":
                ids = last.get("notes") or []
                if index > len(ids):
                    return ToolResult(success=False, message=f"Only {len(ids)} note result(s) available.")
                note_id = ids[index - 1]
                note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
                if not note:
                    return ToolResult(success=False, message="Note result no longer exists.")
                return ToolResult(
                    success=True,
                    data={
                        "workspace_command": "open_window",
                        "window_type": "note_editor",
                        "title": note.title or "Untitled Note",
                        "data": {
                            "note_id": str(note.id),
                            "title": note.title or "",
                            "content": note.content or "",
                            "folder_id": note.folder_id
                        }
                    },
                    message=f"Opening note #{index} from last results."
                )

            docs = last.get("documents") or []
            if index > len(docs):
                return ToolResult(success=False, message=f"Only {len(docs)} document result(s) available.")
            doc_entry = docs[index - 1] or {}
            doc_id = doc_entry.get("id")
            filename = doc_entry.get("filename") or "document"
            if not doc_id:
                return ToolResult(success=False, message="Document result missing ID.")

            doc = db.query(Document).filter(Document.id == doc_id, Document.user_id == user_id).first()
            if not doc:
                return ToolResult(success=False, message="Document result no longer exists.")

            backend_url = (settings.backend_url or "").rstrip("/")
            content_url = f"{backend_url}/documents/{doc.id}/file" if backend_url else f"/documents/{doc.id}/file"
            return ToolResult(
                success=True,
                data={
                    "workspace_command": "open_window",
                    "window_type": "fileviewer",
                    "title": filename,
                    "data": {
                        "filename": filename,
                        "content": content_url,
                        "source": "local"
                    }
                },
                message=f"Opening document #{index} from last results."
            )
        except Exception as e:
            logger.error(f"workspace_open_from_last_results failed: {e}")
            return ToolResult(success=False, message=f"Failed to open result from last search: {str(e)}")
        finally:
            db.close()


# List of all workspace tools for easy import
WORKSPACE_TOOLS = [
    WorkspaceOpenWindowTool(),
    WorkspaceOpenNoteTool(),
    WorkspaceCloseWindowTool(),
    WorkspaceSaveStateTool(),
    WorkspaceArrangeTool(),
    WorkspaceFocusWindowTool(),
    WorkspaceListWindowsTool(),
    WorkspaceFindAndOpenTool(),
    WorkspaceOpenFromLastResultsTool(),
]
