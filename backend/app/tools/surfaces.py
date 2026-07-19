"""
Surface Tools — build/update/tear down ephemeral interactive UI.

Cardinal rule (SURFACES_DESIGN.md §B3): explicit invocation only. Every tool
sets requires_user_origin so the autonomous loop can never spawn a surface; the
`surfaces` tool category is also withheld from default chat schemas and merged
in only when the intent router sees explicit construction language.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult
from app.models.surface import Surface
from app.db.session import get_db
from app.schemas.surface import validate_surface_spec

logger = logging.getLogger(__name__)

_SPEC_HELP = (
    "spec is {\"components\": [...]}. Each component is one of: "
    "markdown {text}, checklist {id, items:[{id,label,checked}], notify}, "
    "steps {id, steps:[{id,text,done}]}, timer {id, label, duration_seconds}, "
    "file_list {id, files}, table {id, columns, rows}, "
    "form {id, fields:[{id,label,kind}]}, buttons {id, buttons:[{id,label,style,notify}]}, "
    "progress {id, value, max, label}. Interactive components need unique ids. "
    "Set notify:true only when a change should wake you (e.g. \"I'm done\")."
)


class SurfaceCreateTool(BaseTool):
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "surface_create"

    @property
    def description(self) -> str:
        return (
            "ONLY when David explicitly asks to build an interactive surface — a "
            "live checklist, a recipe cook-mode with steps/timers, a pickup window "
            "for files, a quick form. Renders from a closed component vocabulary "
            "(no HTML/JS). Components render top-to-bottom in the order given. "
            "For cook-mode / step-by-step, place a `timer` component immediately "
            "AFTER the step it belongs to (split the steps into short `steps` "
            "blocks and interleave the timer for that stage) so a start-timer "
            "control sits right next to the step that needs it — don't dump all "
            "timers at the bottom. " + _SPEC_HELP
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Surface title shown in the header."},
                "spec": {
                    "type": "object",
                    "description": "The render spec: {components: [...]}. " + _SPEC_HELP,
                },
                "expires_in_minutes": {
                    "type": "integer",
                    "description": "Optional auto-expiry in minutes (default 720 = 12h).",
                },
            },
            "required": ["title", "spec"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        title = kwargs.get("title")
        spec = kwargs.get("spec")
        expires_in = kwargs.get("expires_in_minutes")
        conversation_id = kwargs.get("_conversation_id")

        if not title:
            return ToolResult(success=False, message="title is required")
        try:
            normalized = validate_surface_spec(spec)
        except ValueError as e:
            # Corrective error back through the tool loop — model retries in-turn.
            return ToolResult(success=False, message=str(e))

        try:
            minutes = int(expires_in) if expires_in else 720
        except (TypeError, ValueError):
            minutes = 720
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, minutes))

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            surface = Surface(
                id=str(uuid.uuid4()),
                user_id=user_id,
                conversation_id=conversation_id,
                title=title,
                surface_type="custom",
                spec=normalized,
                state={},
                status="active",
                version=1,
                expires_at=expires_at,
            )
            db.add(surface)
            db.commit()
            db.refresh(surface)
            payload = surface.to_dict()
        except Exception as e:
            db.rollback()
            logger.error(f"surface_create: DB write failed: {e}")
            return ToolResult(success=False, message=f"Failed to create surface: {e}")
        finally:
            db.close()

        return ToolResult(
            success=True,
            data={
                "surface_command": "open",
                "surface_id": payload["id"],
                "surface": payload,
            },
            message=f"Opened surface: {title}",
            citations=[f"surface:{payload['id']}"],
        )


class SurfaceUpdateTool(BaseTool):
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "surface_update"

    @property
    def description(self) -> str:
        return (
            "Replace the spec of an existing surface (e.g. advance a recipe, add "
            "items to a checklist). User interaction state is preserved. " + _SPEC_HELP
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "surface_id": {"type": "string", "description": "The surface to update."},
                "spec": {"type": "object", "description": "New render spec. " + _SPEC_HELP},
                "title": {"type": "string", "description": "Optional new title."},
            },
            "required": ["surface_id", "spec"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        surface_id = kwargs.get("surface_id")
        spec = kwargs.get("spec")
        title = kwargs.get("title")

        if not surface_id:
            return ToolResult(success=False, message="surface_id is required")
        try:
            normalized = validate_surface_spec(spec)
        except ValueError as e:
            return ToolResult(success=False, message=str(e))

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            surface = db.query(Surface).filter(
                Surface.id == surface_id, Surface.user_id == user_id
            ).first()
            if not surface:
                return ToolResult(success=False, message=f"Surface not found: {surface_id}")
            if surface.status != "active":
                return ToolResult(success=False, message="Surface is no longer active")

            surface.spec = normalized
            if title:
                surface.title = title
            surface.version = (surface.version or 1) + 1
            db.commit()
            db.refresh(surface)
            payload = surface.to_dict()
        except Exception as e:
            db.rollback()
            logger.error(f"surface_update: DB write failed: {e}")
            return ToolResult(success=False, message=f"Failed to update surface: {e}")
        finally:
            db.close()

        return ToolResult(
            success=True,
            data={
                "surface_command": "update",
                "surface_id": payload["id"],
                "surface": payload,
            },
            message=f"Updated surface: {payload['title']}",
        )


class SurfaceTeardownTool(BaseTool):
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "surface_teardown"

    @property
    def description(self) -> str:
        return "Close and retire a surface when it's no longer needed."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "surface_id": {"type": "string", "description": "The surface to tear down."},
            },
            "required": ["surface_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        surface_id = kwargs.get("surface_id")
        if not surface_id:
            return ToolResult(success=False, message="surface_id is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            surface = db.query(Surface).filter(
                Surface.id == surface_id, Surface.user_id == user_id
            ).first()
            if not surface:
                return ToolResult(success=False, message=f"Surface not found: {surface_id}")
            surface.status = "torn_down"
            db.commit()
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to tear down surface: {e}")
        finally:
            db.close()

        return ToolResult(
            success=True,
            data={"surface_command": "close", "surface_id": surface_id},
            message="Surface closed",
        )


SURFACE_TOOLS = [
    SurfaceCreateTool(),
    SurfaceUpdateTool(),
    SurfaceTeardownTool(),
]
