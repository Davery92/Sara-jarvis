"""Scratchpad chat tools (Phase 10C) — David dictates standing context Sara pins.

Use scratchpad_write when David says to keep something in mind for a while
("meal prepped B/L/D this week", "smoothie every morning on the drive home",
"I'm off Thursday"). These get injected into every chat + deliberation until
they expire, so Sara operates from them instead of hoping to recall them.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class ScratchpadWriteTool(BaseTool):
    @property
    def name(self) -> str:
        return "scratchpad_write"

    @property
    def description(self) -> str:
        return ("Pin a piece of standing context David wants Sara to keep front-of-mind "
                "for a while (a few days to a week). Use for meal-prep status, recurring "
                "plans, temporary schedule changes. category: meals|schedule|errands|other.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The standing context to pin"},
                "category": {"type": "string", "enum": ["meals", "schedule", "errands", "other"]},
            },
            "required": ["content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.scratchpad import write_scratchpad
        r = await write_scratchpad(kwargs.get("content", ""), kwargs.get("category", "other"),
                                   created_from="chat", user_id=user_id)
        if r.get("error"):
            return ToolResult(success=False, message=r["error"])
        return ToolResult(success=True, data=r, message="Pinned — I'll keep that in mind.")


class ScratchpadReadTool(BaseTool):
    @property
    def name(self) -> str:
        return "scratchpad_read"

    @property
    def description(self) -> str:
        return "List the standing context David has pinned (the scratchpad)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.scratchpad import read_scratchpad
        entries = await read_scratchpad(user_id)
        return ToolResult(success=True, data=entries,
                          message=f"{len(entries)} pinned item(s)." if entries else "Nothing pinned.")


class ScratchpadClearTool(BaseTool):
    @property
    def name(self) -> str:
        return "scratchpad_clear"

    @property
    def description(self) -> str:
        return "Clear a pinned scratchpad item (by id) or all of them. Use when David says a standing plan is done/changed."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"entry_id": {"type": "integer", "description": "Omit to clear all"}},
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.scratchpad import clear_scratchpad
        n = await clear_scratchpad(kwargs.get("entry_id"), user_id=user_id)
        return ToolResult(success=True, data={"cleared": n}, message=f"Cleared {n} item(s).")


SCRATCHPAD_TOOLS = [ScratchpadWriteTool(), ScratchpadReadTool(), ScratchpadClearTool()]
