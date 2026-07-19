"""
Workspace job tool — kick off a declared, bounded pipeline.

Per SURFACES_DESIGN §B3 layer 5, this states its plan in chat (the tool message
describes what it will do) and is interruptible. It creates a progress surface
immediately so the user sees the work, then dispatches the Celery task.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult
from app.models.surface import Surface
from app.db.session import get_db
from app.services.workspace_jobs import JOB_REGISTRY, create_job

logger = logging.getLogger(__name__)


class WorkspaceJobRunTool(BaseTool):
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "workspace_job_run"

    @property
    def description(self) -> str:
        return (
            "Run a bounded workspace pipeline over existing data, ONLY on explicit "
            "request. Job types: 'email_attachments_fetch' (params: sender, days) "
            "collects attachments from recent matching emails; 'files_collect' "
            "(params: files=[{name,bucket,key}]) gathers already-stored files. "
            "Opens a progress surface that becomes a downloadable file list when "
            "done. State the plan to David first."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_type": {
                    "type": "string",
                    "enum": ["email_attachments_fetch", "files_collect"],
                },
                "title": {"type": "string", "description": "Short title for the surface."},
                "params": {
                    "type": "object",
                    "description": "Job params. email_attachments_fetch: {sender, days}.",
                },
            },
            "required": ["job_type", "title"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        job_type = kwargs.get("job_type")
        title = kwargs.get("title")
        params = kwargs.get("params") or {}
        conversation_id = kwargs.get("_conversation_id")

        if job_type not in JOB_REGISTRY:
            return ToolResult(success=False, message=f"Unknown job_type '{job_type}'")
        if not title:
            return ToolResult(success=False, message="title is required")

        params = {**params, "title": title}

        # Create the progress surface first so the user sees the work immediately.
        db: Session = next(get_db())
        try:
            surface = Surface(
                id=str(uuid.uuid4()),
                user_id=user_id,
                conversation_id=conversation_id,
                title=title,
                surface_type="custom",
                spec={"components": [
                    {"type": "markdown", "text": f"### {title}"},
                    {"type": "progress", "id": "p", "value": 5, "max": 100, "label": "Starting…"},
                ]},
                state={},
                status="active",
                version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
            db.add(surface)
            db.commit()
            db.refresh(surface)
            surface_payload = surface.to_dict()
            surface_id = surface.id
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to open surface: {e}")
        finally:
            db.close()

        job = create_job(user_id, job_type, params, surface_id)

        # Dispatch async; fall back to inline if the broker is unavailable.
        try:
            from app.tasks.workspace_jobs import run_workspace_job
            run_workspace_job.delay(job.id)
            dispatched = "dispatched"
        except Exception as e:
            logger.warning(f"workspace_job dispatch failed, running inline: {e}")
            from app.services.workspace_jobs import run_job
            run_job(job.id)
            dispatched = "ran inline"

        return ToolResult(
            success=True,
            data={
                "surface_command": "open",
                "surface_id": surface_id,
                "surface": surface_payload,
                "job_id": job.id,
            },
            message=f"Started '{title}' ({job_type}, {dispatched}). I'll drop the files in the surface when it's done.",
            citations=[f"workspace_job:{job.id}"],
        )


WORKSPACE_JOB_TOOLS = [WorkspaceJobRunTool()]
