"""
Authoring Tools

Sara-built real files. `document_generate` turns a markdown body into a
downloadable Word or PDF file that lands in the Artifacts Studio with a
download button. `artifact_read` fetches an artifact's content/source so a
follow-up "tighten section 2 and re-export" is a regenerate, not an
edit-the-binary problem.

Cardinal rule (SURFACES_DESIGN.md §A5): explicit invocation only. Both tools
set requires_user_origin so the autonomous loop can never fabricate files.
"""

import uuid
import logging
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult
from app.models.artifact import Artifact
from app.db.session import get_db
from app.services.document_renderer import render_document

logger = logging.getLogger(__name__)


class DocumentGenerateTool(BaseTool):
    """Generate a downloadable Word/PDF document from markdown."""

    # Files are only ever produced on an explicit user request — never from
    # deliberation, reactive, or Celery paths.
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "document_generate"

    @property
    def description(self) -> str:
        return (
            "Produce a real .docx or .pdf from a markdown body; it lands in the "
            "Studio with a download button. This is THE way to make a document or "
            "PDF — always use it for that, never hand-build files or dispatch a "
            "background/VM coding agent to write a PDF. If the document needs data "
            "(e.g. \"a PDF of my nutrition this week\"), gather that data with the "
            "relevant tools first, then call this with the assembled markdown. "
            "ONLY when David explicitly asks for a document/file; if you merely "
            "think one would help, offer it in chat and wait for his yes. To revise "
            "an existing document, pass its artifact_id to regenerate in place."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["docx", "pdf"],
                    "description": "File format: 'docx' for Word, 'pdf' for PDF.",
                },
                "title": {
                    "type": "string",
                    "description": "Document title (also the filename).",
                },
                "content": {
                    "type": "string",
                    "description": "Full document body in markdown.",
                },
                "style": {
                    "type": "string",
                    "enum": ["default", "letter", "report"],
                    "description": "Layout preset. 'report' adds a title page + page numbers.",
                },
                "artifact_id": {
                    "type": "string",
                    "description": "Optional. Regenerate/replace this existing document artifact.",
                },
            },
            "required": ["format", "title", "content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        fmt = (kwargs.get("format") or "").lower()
        title = kwargs.get("title")
        content = kwargs.get("content")
        style = kwargs.get("style") or "default"
        artifact_id = kwargs.get("artifact_id")

        if fmt not in ("docx", "pdf"):
            return ToolResult(success=False, message="format must be 'docx' or 'pdf'")
        if not title:
            return ToolResult(success=False, message="title is required")
        if not content:
            return ToolResult(success=False, message="content (markdown body) is required")

        # Render the file.
        try:
            file_bytes, filename, mime = render_document(fmt, title, content, style)
        except RuntimeError as e:
            # PDF deps not installed yet (pre-A-3) — steer to docx.
            return ToolResult(success=False, message=str(e))
        except Exception as e:
            logger.error(f"document_generate: render failed: {e}")
            return ToolResult(success=False, message=f"Failed to render document: {e}")

        # Store bytes in object storage.
        try:
            from app.services.docs_ingest import DocumentProcessor
            storage_key = await DocumentProcessor().store_file(file_bytes, filename, mime)
        except Exception as e:
            logger.error(f"document_generate: storage failed: {e}")
            return ToolResult(success=False, message=f"Failed to store document: {e}")

        file_content = {
            "storage_key": storage_key,
            "filename": filename,
            "mime": mime,
            "size_bytes": len(file_bytes),
            "format": fmt,
            "source_markdown": content,
        }

        # Persist / update the Artifact row.
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            existing = None
            if artifact_id:
                existing = db.query(Artifact).filter(
                    Artifact.id == artifact_id,
                    Artifact.user_id == user_id,
                ).first()

            if existing:
                version = int((existing.artifact_metadata or {}).get("version", 1)) + 1
                existing.title = title
                existing.content = file_content
                existing.artifact_metadata = {
                    **(existing.artifact_metadata or {}),
                    "source": "document_generate",
                    "version": version,
                }
                db.commit()
                db.refresh(existing)
                row_id = existing.id
                message = f"Regenerated {fmt.upper()} (v{version}): {filename}"
            else:
                artifact = Artifact(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    artifact_type="file",
                    title=title,
                    content=file_content,
                    artifact_metadata={"source": "document_generate", "version": 1},
                    is_pinned=False,
                )
                db.add(artifact)
                db.commit()
                db.refresh(artifact)
                row_id = artifact.id
                message = f"Created {fmt.upper()}: {filename}"
        except Exception as e:
            db.rollback()
            logger.error(f"document_generate: DB write failed: {e}")
            return ToolResult(success=False, message=f"Failed to save document: {e}")
        finally:
            db.close()

        # Open the file artifact in the canvas immediately; it's in the Studio
        # permanently. The frontend renders a file card + download button.
        return ToolResult(
            success=True,
            data={
                "canvas_command": "open",
                "artifact_type": "file",
                "title": title,
                "artifact_id": row_id,
                "content": {**file_content, "artifact_id": row_id},
            },
            message=message,
            citations=[f"artifact:{row_id}"],
        )


class ArtifactReadTool(BaseTool):
    """Read an artifact's content/source — used to revise a document."""

    @property
    def name(self) -> str:
        return "artifact_read"

    @property
    def description(self) -> str:
        return (
            "Fetch an artifact's content by id — including a generated document's "
            "source markdown — so you can revise it and re-export. Use before "
            "regenerating a document the user asked you to change."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "The id of the artifact to read.",
                },
            },
            "required": ["artifact_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        artifact_id = kwargs.get("artifact_id")
        if not artifact_id:
            return ToolResult(success=False, message="artifact_id is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            artifact = db.query(Artifact).filter(
                Artifact.id == artifact_id,
                Artifact.user_id == user_id,
            ).first()
            if not artifact:
                return ToolResult(success=False, message=f"Artifact not found: {artifact_id}")

            content = dict(artifact.content or {})
            # Don't echo the storage key back to the model — it's not useful and
            # keeps the tool result compact.
            content.pop("storage_key", None)
            return ToolResult(
                success=True,
                data={
                    "id": artifact.id,
                    "artifact_type": artifact.artifact_type,
                    "title": artifact.title,
                    "content": content,
                },
                message=f"Read artifact: {artifact.title}",
                citations=[f"artifact:{artifact.id}"],
            )
        finally:
            db.close()


AUTHORING_TOOLS = [
    DocumentGenerateTool(),
    ArtifactReadTool(),
]
