"""
Tool for sending directives from David to Sara's autonomous cognition system (ACS).

When David tells Sara things like "tell ACS to stop researching X" or "tell your
autonomous self to focus on Y", Sara calls this tool to create a directive that
the ACS reads at session start and checks mid-session.
"""

import logging
import uuid
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

VALID_TYPES = ("focus", "stop", "context", "redirect", "question")
VALID_PRIORITIES = ("urgent", "normal", "low")
TYPE_ALIASES = {
    "research": "focus",
    "explore": "focus",
    "monitor": "context",
    "create": "redirect",
    "reflect": "question",
    "custom": "context",
}


class SendACSDirectiveTool(BaseTool):
    """Send a directive to Sara's autonomous cognition system."""

    @property
    def name(self) -> str:
        return "send_acs_directive"

    @property
    def description(self) -> str:
        return (
            "Send a directive to Sara's autonomous cognition system (ACS). "
            "Use when David wants to communicate with the ACS: tell it to stop "
            "doing something, focus on something, give it context, redirect its "
            "work, or ask it a question. The directive will be picked up at the "
            "next session start or within a few turns of a running session."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directive_type": {
                    "type": "string",
                    "enum": list(VALID_TYPES),
                    "description": (
                        "Type of directive: "
                        "'stop' = stop doing something, "
                        "'focus' = prioritize this topic, "
                        "'redirect' = change course, "
                        "'context' = FYI information, "
                        "'question' = David asks ACS something"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "The directive message — be specific about what to do or stop doing",
                },
                "priority": {
                    "type": "string",
                    "enum": list(VALID_PRIORITIES),
                    "description": "Priority level (default: normal). Use 'urgent' for stop directives.",
                },
            },
            "required": ["directive_type", "content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        directive_type = kwargs.get("directive_type", "").strip()
        content = kwargs.get("content", "").strip()
        priority = kwargs.get("priority", "normal").strip()
        directive_type = TYPE_ALIASES.get(directive_type, directive_type)

        if not directive_type or directive_type not in VALID_TYPES:
            return ToolResult(success=False, message=f"Invalid directive_type. Must be one of: {', '.join(VALID_TYPES)}")
        if not content:
            return ToolResult(success=False, message="Content is required")
        if priority not in VALID_PRIORITIES:
            priority = "normal"

        # Auto-escalate stop directives
        if directive_type == "stop" and priority != "urgent":
            priority = "urgent"

        try:
            from app.db.session import get_async_session_factory
            from sqlalchemy import text

            directive_id = str(uuid.uuid4())
            async_session = get_async_session_factory()

            async with async_session() as db:
                await db.execute(text("""
                    INSERT INTO acs_directive (id, user_id, directive_type, content, priority, status, source)
                    VALUES (:id, :uid, :dtype, :content, :priority, 'pending', 'david_chat')
                """), {
                    "id": directive_id, "uid": user_id, "dtype": directive_type,
                    "content": content, "priority": priority,
                })
                await db.commit()

            # Publish to Redis for immediate pickup by running session
            try:
                import json
                import os
                import redis.asyncio as aioredis
                REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                r = await aioredis.from_url(REDIS_URL, decode_responses=True)
                try:
                    await r.publish(
                        f"sara:acs:directives:{user_id}",
                        json.dumps({
                            "id": directive_id, "directive_type": directive_type,
                            "content": content, "priority": priority,
                        }),
                    )
                finally:
                    if hasattr(r, "aclose"):
                        await r.aclose()
                    else:
                        await r.close()
            except Exception as e:
                logger.warning(f"Failed to publish directive to Redis: {e}")

            type_labels = {
                "stop": "Told my autonomous self to STOP",
                "focus": "Directed my autonomous self to FOCUS on",
                "redirect": "Redirected my autonomous self:",
                "context": "Sent context to my autonomous self:",
                "question": "Asked my autonomous self:",
            }
            prefix = type_labels.get(directive_type, "Sent to ACS:")

            return ToolResult(
                success=True,
                data={"directive_id": directive_id, "directive_type": directive_type, "priority": priority},
                message=f"{prefix} {content[:100]}. It will be picked up at the next opportunity.",
            )

        except Exception as e:
            logger.error(f"Failed to send ACS directive: {e}")
            return ToolResult(success=False, message=f"Failed to send directive: {e}")


ACS_DIRECTIVE_TOOLS = [SendACSDirectiveTool()]
