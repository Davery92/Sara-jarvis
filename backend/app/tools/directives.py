"""Directive chat tools (Phase 12B) — corrections with permanent teeth.

When David states a standing rule or corrects a recurring behavior ("stop
bringing up X", "always use ET", "never ping me before 9 on weekends"), Sara
saves it as a directive — behavioral law injected into every prompt thereafter.
The JIT saga happened because corrections didn't stick; directives make them
permanent. Propose saving a directive whenever you detect a correction.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class SaveDirectiveTool(BaseTool):
    @property
    def name(self) -> str:
        return "save_directive"

    @property
    def description(self) -> str:
        return ("Save a standing rule / correction from David as a permanent directive "
                "(always followed thereafter). Use when he states a lasting preference or "
                "corrects a recurring behavior: 'never bring up X', 'always do Y', "
                "'don't ping me before 9 on weekends'. Confirm with him, then save it once.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The rule, in imperative form"},
                "category": {"type": "string", "description": "e.g. topics, timing, tone, privacy"},
            },
            "required": ["text"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.directives import add_directive
        r = await add_directive(kwargs.get("text", ""), kwargs.get("category", "general"), user_id)
        if r.get("error"):
            return ToolResult(success=False, message=r["error"])
        if r.get("duplicate"):
            return ToolResult(success=True, data=r, message="Already got that one — it stands.")
        return ToolResult(success=True, data=r, message="Got it — that's a standing rule now. I'll always follow it.")


class ListDirectivesTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_directives"

    @property
    def description(self) -> str:
        return "List the standing rules David has given Sara ('things you've told me')."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.directives import list_directives
        ds = await list_directives(user_id)
        return ToolResult(success=True, data=ds, message=f"{len(ds)} standing rule(s)." if ds else "No standing rules yet.")


class RemoveDirectiveTool(BaseTool):
    @property
    def name(self) -> str:
        return "remove_directive"

    @property
    def description(self) -> str:
        return "Remove a standing directive by id when David rescinds a rule."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"directive_id": {"type": "integer"}}, "required": ["directive_id"]}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.directives import remove_directive
        n = await remove_directive(int(kwargs["directive_id"]), user_id)
        return ToolResult(success=True, data={"removed": n}, message=f"Removed {n} rule(s).")


DIRECTIVE_TOOLS = [SaveDirectiveTool(), ListDirectivesTool(), RemoveDirectiveTool()]
