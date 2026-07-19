"""Quiet / guest mode chat tool (Phase 11E)."""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class QuietModeTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_quiet_mode"

    @property
    def description(self) -> str:
        return ("Turn quiet mode on/off. Quiet mode suspends all of Sara's proactive "
                "outreach and autonomous home actions (reactive chat still works). Use "
                "when David says 'be quiet', 'stop bugging me', 'do not disturb', 'guests over'. "
                "action: 'on' | 'off'. Set guest=true for guest mode (also pauses pattern learning).")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["on", "off"]},
                "hours": {"type": "number", "description": "How long (omit = until turned off)"},
                "guest": {"type": "boolean", "description": "Guest mode (also pauses learning)"},
            },
            "required": ["action"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.quiet_mode import set_quiet, clear_quiet
        if kwargs.get("action") == "off":
            clear_quiet()
            return ToolResult(success=True, message="Quiet mode off — I'll be my usual proactive self again.")
        r = set_quiet(hours=kwargs.get("hours"), guest=bool(kwargs.get("guest")))
        if r.get("error"):
            return ToolResult(success=False, message=r["error"])
        span = f"for {kwargs['hours']}h" if kwargs.get("hours") else "until you turn it back on"
        mode = "Guest mode" if kwargs.get("guest") else "Quiet mode"
        return ToolResult(success=True, data=r,
                          message=f"{mode} on {span} — I'll keep watching but won't reach out or touch the house.")


QUIET_TOOLS = [QuietModeTool()]
