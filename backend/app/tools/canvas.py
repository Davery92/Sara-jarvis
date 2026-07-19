"""
Canvas Control Tools

Tools for Sara to control the canvas panel in the chat interface.
These tools return structured data that the frontend interprets to
open, update, or close the canvas with specific content types.
"""

import uuid
import logging
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.models.artifact import Artifact
from app.services.embeddings import get_embedding
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CanvasOpenTool(BaseTool):
    """Tool for opening the canvas with specific content"""

    @property
    def name(self) -> str:
        return "canvas_open"

    @property
    def description(self) -> str:
        return """Open the canvas panel with specific content. Use this to show code snippets,
documents, mindmaps, or diagrams to the user. The canvas appears as a side panel next to the chat."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_type": {
                    "type": "string",
                    "enum": ["code", "document", "mindmap", "diagram"],
                    "description": "Type of content: 'code' for code snippets, 'document' for markdown text, 'mindmap' for interactive mind maps, 'diagram' for mermaid diagrams"
                },
                "title": {
                    "type": "string",
                    "description": "Title for the canvas content"
                },
                "content": {
                    "type": "object",
                    "description": "Content object. For 'code': {code, language}. For 'document': {content, format}. For 'mindmap': {nodes, edges}. For 'diagram': {source, type}."
                }
            },
            "required": ["artifact_type", "title", "content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Open the canvas with specified content"""

        artifact_type = kwargs.get("artifact_type")
        title = kwargs.get("title")
        content = kwargs.get("content")

        if not artifact_type:
            return ToolResult(
                success=False,
                message="artifact_type is required"
            )

        if not title:
            return ToolResult(
                success=False,
                message="title is required"
            )

        if not content:
            return ToolResult(
                success=False,
                message="content is required"
            )

        # Validate content structure based on type
        if artifact_type == "code":
            if not isinstance(content, dict) or "code" not in content:
                return ToolResult(
                    success=False,
                    message="Code content must have 'code' field"
                )
            # Default language if not specified
            if "language" not in content:
                content["language"] = "plaintext"

        elif artifact_type == "document":
            if not isinstance(content, dict) or "content" not in content:
                return ToolResult(
                    success=False,
                    message="Document content must have 'content' field"
                )
            if "format" not in content:
                content["format"] = "markdown"

        elif artifact_type == "mindmap":
            if not isinstance(content, dict):
                content = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
            if "nodes" not in content:
                content["nodes"] = []
            if "edges" not in content:
                content["edges"] = []
            if "viewport" not in content:
                content["viewport"] = {"x": 0, "y": 0, "zoom": 1}

        elif artifact_type == "diagram":
            if not isinstance(content, dict) or "source" not in content:
                return ToolResult(
                    success=False,
                    message="Diagram content must have 'source' field (mermaid syntax)"
                )
            if "type" not in content:
                content["type"] = "mermaid"

        # Persist the artifact row first so everything Sara builds lands in the
        # Studio library by construction, then emit the command including its id.
        # A failure to persist must not break the in-conversation canvas, so we
        # fall back to an unsaved (id-less) command on any DB error.
        artifact_id: Optional[str] = None
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            artifact = Artifact(
                id=str(uuid.uuid4()),
                user_id=user_id,
                artifact_type=artifact_type,
                title=title,
                content=content,
                artifact_metadata={"source": "canvas_open"},
                is_pinned=False,
            )
            db.add(artifact)
            db.commit()
            db.refresh(artifact)
            artifact_id = artifact.id
        except Exception as e:
            db.rollback()
            logger.warning(f"canvas_open: failed to persist artifact row: {e}")
        finally:
            db.close()

        data = {
            "canvas_command": "open",
            "artifact_type": artifact_type,
            "title": title,
            "content": content,
        }
        if artifact_id:
            data["artifact_id"] = artifact_id

        return ToolResult(
            success=True,
            data=data,
            message=f"Opening {artifact_type} canvas: {title}"
        )


class CanvasUpdateTool(BaseTool):
    """Tool for updating the current canvas content"""

    @property
    def name(self) -> str:
        return "canvas_update"

    @property
    def description(self) -> str:
        return "Update the content of the currently open canvas. Use this to modify code, add nodes to a mindmap, or update document text."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "object",
                    "description": "New content to update the canvas with. Structure depends on canvas type."
                },
                "title": {
                    "type": "string",
                    "description": "Optional new title for the canvas"
                }
            },
            "required": ["content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Update the current canvas content"""

        content = kwargs.get("content")
        title = kwargs.get("title")

        if not content:
            return ToolResult(
                success=False,
                message="content is required"
            )

        result_data = {
            "canvas_command": "update",
            "content": content
        }

        if title:
            result_data["title"] = title

        return ToolResult(
            success=True,
            data=result_data,
            message="Canvas content updated"
        )


class CanvasCloseTool(BaseTool):
    """Tool for closing the canvas panel"""

    @property
    def name(self) -> str:
        return "canvas_close"

    @property
    def description(self) -> str:
        return "Close the canvas panel. Use this when done showing content to the user."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Close the canvas"""

        return ToolResult(
            success=True,
            data={
                "canvas_command": "close"
            },
            message="Canvas closed"
        )


class CanvasOpenNoteTool(BaseTool):
    """Tool for opening an existing note in the canvas"""

    @property
    def name(self) -> str:
        return "canvas_open_note"

    @property
    def description(self) -> str:
        return """Open an existing note in the canvas for viewing or editing.
The note will appear in the canvas panel and any edits will be auto-saved back to the notes system.
You can specify either the note ID or search by title."""

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
        """Open a note in the canvas"""

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

            # Return canvas command with note content
            return ToolResult(
                success=True,
                data={
                    "canvas_command": "open",
                    "artifact_type": "note",
                    "title": note.title or "Untitled",
                    "content": {
                        "note_id": str(note.id),
                        "title": note.title or "",
                        "content": note.content,
                        "folder_id": note.folder_id
                    },
                    "note_id": str(note.id)
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


class CanvasSaveAsNoteTool(BaseTool):
    """Tool for saving canvas content as a new note"""

    @property
    def name(self) -> str:
        return "canvas_save_as_note"

    @property
    def description(self) -> str:
        return """Save the current canvas content as a new note.
This creates a new note from the canvas content (code, document, or mindmap).
The content will be converted to markdown format."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the new note"
                },
                "content": {
                    "type": "string",
                    "description": "The content to save (markdown format)"
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional folder ID to save the note in"
                }
            },
            "required": ["title", "content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Save canvas content as a new note"""

        title = kwargs.get("title")
        content = kwargs.get("content")
        folder_id = kwargs.get("folder_id")

        if not title:
            return ToolResult(
                success=False,
                message="title is required"
            )

        if not content:
            return ToolResult(
                success=False,
                message="content is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Get embedding for the note
            full_text = f"{title}\n{content}"
            embedding = await get_embedding(full_text)

            # Create note
            note = Note(
                user_id=user_id,
                title=title,
                content=content,
                folder_id=folder_id,
                embedding=embedding
            )

            db.add(note)
            db.commit()
            db.refresh(note)

            return ToolResult(
                success=True,
                data={
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "folder_id": note.folder_id,
                    "created_at": note.created_at.isoformat()
                },
                message=f"Saved canvas as note: {title}",
                citations=[f"note:{note.id}"]
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to save note: {str(e)}"
            )
        finally:
            db.close()
