"""acknowledge_notifications chat tool (Phase 12K).

When David replies to notifications Sara sent ("saw your messages — yes to the first
two, skip the gym thing"), call this once with his answers. It marks each read,
records the ones he actually responded to as engaged, clears the linked inbox items
+ badge on every surface, and stops any follow-up thread from re-nagging.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class AcknowledgeNotificationsTool(BaseTool):
    @property
    def name(self) -> str:
        return "acknowledge_notifications"

    @property
    def description(self) -> str:
        return ("Acknowledge notifications David is replying to. `ids` is a list of the "
                "notification ids (from the 'Sent but unacknowledged' context block), or the "
                "string \"all\" for a blanket 'saw your messages'. `responses` optionally maps "
                "an id to what David said about it — only those count as *engaged* (acted on); "
                "the rest are cleared as read-but-not-engaged. Clears web + iOS badges and stops "
                "responded follow-ups from re-nagging. Call once per reply, not per item.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ids": {
                    "description": "List of notification ids, or the string \"all\".",
                    "oneOf": [
                        {"type": "array", "items": {"type": "integer"}},
                        {"type": "string", "enum": ["all"]},
                    ],
                },
                "responses": {
                    "type": "object",
                    "description": "Optional map of notification id -> David's response note",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["ids"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        ids = kwargs.get("ids")
        if ids is None:
            return ToolResult(success=False, message="ids is required (a list or \"all\").")
        from app.services.notification_ack import acknowledge
        r = await acknowledge(user_id, ids, kwargs.get("responses"))
        if r["count"] == 0:
            return ToolResult(success=True, data=r, message="Nothing to acknowledge.")
        badge = r.get("badge")
        tail = f" Badge now {badge}." if badge is not None else ""
        return ToolResult(success=True, data=r,
                          message=f"Acknowledged {r['count']} ({r['engaged']} you acted on).{tail}")


NOTIFICATION_ACK_TOOLS = [AcknowledgeNotificationsTool()]
