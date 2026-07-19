"""Interest feedback chat tool (Phase 6.3).

When David pushes back on a topic Sara keeps surfacing ("stop telling me about
X", "I don't care about Y"), Sara records the reaction here. Two strikes and the
interest auto-mutes via the existing `blocked` flag — so a couple of quiet
dismissals catch it before David has to rage-type in all caps.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class ReactToInterestTool(BaseTool):
    @property
    def name(self) -> str:
        return "react_to_interest"

    @property
    def description(self) -> str:
        return ("Record David's reaction to a topic/interest Sara has been surfacing. "
                "Use when he pushes back ('stop bringing up X', 'I don't care about Y', "
                "'quit updating me on Z'). reaction='negative' for explicit pushback, "
                "'dismiss' for a shrug, 'rage' for all-caps fury (instant mute), "
                "'positive' when he's engaged. Two strikes auto-mutes the interest "
                "(reversible; never deleted).")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The interest topic or name David reacted to"},
                "reaction": {"type": "string", "enum": ["negative", "dismiss", "ignore", "rage", "positive"],
                             "description": "David's reaction"},
                "note": {"type": "string", "description": "Optional: what he actually said"},
            },
            "required": ["topic", "reaction"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        topic = (kwargs.get("topic") or "").strip()
        reaction = (kwargs.get("reaction") or "").strip()
        if not topic or not reaction:
            return ToolResult(success=False, message="topic and reaction are required.")
        from app.services.interest_feedback import record_reaction
        res = await record_reaction(topic, reaction, note=kwargs.get("note", ""))
        if res.get("error"):
            return ToolResult(success=False, message=res["error"])
        if res.get("just_muted"):
            msg = f"Muted '{res['interest']}' — I won't bring it up again (you can unmute it in settings)."
        elif res.get("muted"):
            msg = f"'{res['interest']}' is already muted."
        else:
            msg = f"Noted ({reaction}) — '{res['interest']}' now at {res['strikes']} strike(s)."
        return ToolResult(success=True, data=res, message=msg)


INTEREST_TOOLS = [ReactToInterestTool()]
