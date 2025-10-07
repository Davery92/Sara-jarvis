"""Shadow Mode tool for AI-assisted work capture"""
from typing import Optional
from app.tools.base import BaseTool, ToolResult
from app.services.shadow_session_service import shadow_session_service
import logging

logger = logging.getLogger(__name__)


class ShadowStartTool(BaseTool):
    """Start a Shadow Mode session to capture work activity"""

    name = "start_shadow_session"
    description = "Start a SHADOW MODE session (NOT a timer) to automatically capture browser activity, VS Code files, tasks, decisions, and ideas from a desktop agent. Use this when the user says 'shadow me', 'start shadow mode', 'shadow session', or wants to track their work activity automatically."

    parameters = {
        "type": "object",
        "properties": {
            "duration_minutes": {
                "type": "integer",
                "description": "Duration of the session in minutes (e.g., 2, 30, 60, 90)"
            },
            "context": {
                "type": "string",
                "description": "Optional context describing what you'll be working on"
            }
        },
        "required": []
    }

    async def execute(
        self,
        user_id: str,
        duration_minutes: Optional[int] = None,
        context: Optional[str] = None
    ) -> ToolResult:
        """Execute the shadow session start"""
        try:
            # Start shadow session
            session = await shadow_session_service.start_session(
                user_id=user_id,
                duration_minutes=duration_minutes,
                context=context
            )

            duration_text = f"{duration_minutes} minutes" if duration_minutes else "an unlimited time"
            context_text = f" (Context: {context})" if context else ""

            return ToolResult(
                success=True,
                message=f"✅ Shadow session started for {duration_text}{context_text}. Session ID: {session.id}",
                data={
                    "session_id": session.id,
                    "started_at": session.started_at.isoformat(),
                    "duration_minutes": duration_minutes,
                    "context": context
                }
            )
        except Exception as e:
            logger.error(f"Failed to start shadow session: {e}")
            return ToolResult(
                success=False,
                message=f"❌ Failed to start shadow session: {str(e)}"
            )
