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


class ClearInboxItemsTool(BaseTool):
    """Clear ANY inbox item David addresses in chat — not just notifications.

    The inbox badge counts attention items + task clarifications + notifications,
    and the inbox digest lists all of them with a `kind` and `id`. Use THIS tool
    (not acknowledge_notifications) whenever David responds to items from the
    inbox digest, so the badge actually drops on web and iOS.
    """

    @property
    def name(self) -> str:
        return "clear_inbox_items"

    @property
    def description(self) -> str:
        return (
            "Clear the inbox items David just addressed, of ANY kind (attention, "
            "notification, clarification, capture) — this is what drops the badge. "
            "Pass one entry per item he responded to, using the exact `kind` and `id` "
            "from the inbox digest. `disposition`: 'engaged' (he acted on / answered it) "
            "or 'dismissed' (not relevant). `response`: what he said — REQUIRED to answer "
            "a clarification (it resumes the blocked task); optional otherwise. Call once "
            "per reply. Use this instead of acknowledge_notifications when the digest was loaded."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "The inbox items David addressed.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["attention", "notification", "clarification", "capture"],
                                "description": "The item's kind, from its digest ref tag.",
                            },
                            "id": {
                                "description": "The item's id from the digest (uuid, or integer for notifications).",
                                "type": ["string", "integer"],
                            },
                            "disposition": {
                                "type": "string",
                                "enum": ["engaged", "dismissed"],
                                "description": "engaged = he acted on/answered it; dismissed = not relevant.",
                            },
                            "response": {
                                "type": "string",
                                "description": "What David said. Required to answer a clarification.",
                            },
                        },
                        "required": ["kind", "id"],
                    },
                },
            },
            "required": ["items"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        items = kwargs.get("items")
        if not items:
            return ToolResult(success=False, message="items is required (a list of {kind, id}).")
        from app.services.notification_ack import resolve_inbox_items
        r = await resolve_inbox_items(user_id, items)
        if r["cleared"] == 0:
            return ToolResult(success=True, data=r, message="Nothing cleared (check kinds/ids).")
        c = r["counts"]
        parts = [f"{c[k]} {k}" for k in ("attention", "notification", "clarification", "capture") if c.get(k)]
        badge = r.get("badge")
        tail = f" Badge now {badge}." if badge is not None else ""
        return ToolResult(success=True, data=r,
                          message=f"Cleared {', '.join(parts)}.{tail}")


NOTIFICATION_ACK_TOOLS = [AcknowledgeNotificationsTool(), ClearInboxItemsTool()]
