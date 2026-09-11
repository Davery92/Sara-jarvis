"""`find_tools` — the model's own escape hatch out of the 35-tool diet.

Phase 2 of SARA_CHAT_HARNESS_REBUILD_PLAN_2026_09_11. Retrieval picks the
tools that look relevant to what David just said, but a conversation drifts:
he asks about email, then wants the attachments filed, then wants the Studio.
Rather than growing the tool list forever (the 94-schema failure), the model
asks for what it needs by describing the need in words.

The schemas found here are appended to the live tool list for the rest of the
turn (StreamingChatClient mutates `self._active_tools`) and stick to the
conversation so the next turn starts with them already loaded.
"""

import logging
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class FindToolsTool(BaseTool):
    @property
    def name(self) -> str:
        return "find_tools"

    @property
    def description(self) -> str:
        return (
            "Find and load tools you do not currently have. Describe what you need to do "
            "in plain words ('file email attachments somewhere David can download them', "
            "'turn off a light', 'check a server'). Returns the matching tools AND makes "
            "them callable for the rest of this conversation. Call this before telling "
            "David you cannot do something — the registry has ~300 tools and only a few "
            "are loaded on any given turn."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "need": {
                    "type": "string",
                    "description": "What you are trying to do, in plain words.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many tools to load (default 6, max 10).",
                },
            },
            "required": ["need"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        need = (kwargs.get("need") or "").strip()
        if not need:
            return ToolResult(
                success=False,
                message="Say what you are trying to do and I'll find the tool for it.",
            )
        try:
            limit = int(kwargs.get("limit") or 6)
        except (TypeError, ValueError):
            limit = 6
        limit = max(1, min(limit, 10))

        from app.services.tool_retrieval import ToolIndex

        # `need` is often shorter than a user sentence; retrieve() ignores very
        # short queries, so pad the intent rather than lowering the global floor.
        names = await ToolIndex.retrieve(f"tool to {need}", k=limit)
        if not names:
            return ToolResult(
                success=True,
                data={"tools": []},
                message=(
                    f"No tool matches '{need}'. Tell David plainly that this is not "
                    "something you can do yet — do not improvise with web_search or a shell."
                ),
            )

        described = ToolIndex.describe(names)
        return ToolResult(
            success=True,
            data={"tools": described, "loaded": names},
            message=(
                "Loaded "
                + str(len(names))
                + " tools for the rest of this conversation: "
                + ", ".join(names)
                + ". Call the right one now."
            ),
        )
