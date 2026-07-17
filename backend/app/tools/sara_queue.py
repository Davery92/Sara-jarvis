"""Queue work for Sara's autonomous mind (the ACS daemon inbox).

This is the chat-side half of "just tell her to do it": when David asks for
something that should be pursued autonomously — multi-day work, building
something, an open-ended investigation — the chat LLM queues it here. The
daemon sees it in ambient context within a tick, picks it up, and (for work
bigger than one sitting) turns it into a persistent goal she advances on her
own across days.
"""

import logging
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class QueueForSaraTool(BaseTool):
    """Queue a prompt into Sara's autonomous (ACS) inbox."""

    # Only a real chat turn from David may hand work to the daemon — the
    # autonomous loop must not queue items to itself through this tool.
    requires_user_origin = True

    @property
    def name(self) -> str:
        return "queue_for_sara"

    @property
    def description(self) -> str:
        return (
            "Hand work to your autonomous mind (the always-on daemon) to pursue "
            "independently over hours or days. Use when David asks you to 'go do', "
            "build, investigate, or figure something out that is bigger than this "
            "conversation — the daemon will pick it up, plan it as a goal, and work "
            "it with web research and sandbox machines. Do NOT use for quick "
            "questions answerable right now, or for one-shot agent tasks "
            "(dispatch_agent_task covers those)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What David wants done, phrased as a directive to your future self.",
                },
                "context": {
                    "type": "string",
                    "description": "Anything from this conversation your daemon will need (links, constraints, prior decisions).",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "How soon she should pick it up. Default normal.",
                },
            },
            "required": ["prompt"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, message="prompt is required")
        context = (kwargs.get("context") or "").strip() or None
        urgency = kwargs.get("urgency") or "normal"
        if urgency not in ("low", "normal", "high"):
            urgency = "normal"

        try:
            from sqlalchemy import text
            from app.db.session import get_async_session_factory

            async_session = get_async_session_factory()
            async with async_session() as db:
                row = (await db.execute(
                    text("""
                        INSERT INTO sara_inbox (created_by, urgency, prompt, context)
                        VALUES ('david_chat', :urgency, :prompt, :context)
                        RETURNING id, created_at
                    """),
                    {"urgency": urgency, "prompt": prompt[:4000],
                     "context": context[:8000] if context else None},
                )).mappings().first()
                await db.commit()

            return ToolResult(
                success=True,
                message=(
                    f"Queued for your autonomous mind (inbox item {str(row['id'])[:8]}). "
                    "Tell David it's handed off and you'll work it independently — "
                    "he'll hear from you once, when there's something real to show."
                ),
                data={"inbox_id": str(row["id"]), "urgency": urgency},
            )
        except Exception as e:
            logger.exception("queue_for_sara failed")
            return ToolResult(success=False, message=f"Failed to queue: {e}")
