"""resolve_thread — the tool Sara did not have.

On 2026-09-02 David said "ENOUGH WITH THE LAURA WEIPPERT OVERDUE NONSENSE WE HAD
OUR MEETING" and Sara answered, accurately, that she had no way to close a thread.
She cancelled two unrelated reminders instead, and the three Laura threads stayed
open. This is that missing verb.
"""

from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class ResolveThreadTool(BaseTool):
    @property
    def name(self) -> str:
        return "resolve_thread"

    @property
    def description(self) -> str:
        return (
            "Close an open thread because it is actually finished — David says he "
            "already did it, the meeting happened, the email was answered, or he "
            "tells you to stop bringing it up. Pass `query` with the distinctive "
            "words (a person's name, the subject) or `thread_id` if you have one. "
            "This resolves the thread, drops anything queued to say about it, and "
            "marks its notifications read, so it will not come back. Use it the "
            "moment David indicates something is handled — do not just agree."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Distinctive words identifying the thread — a person's name "
                        "or the subject. Not filler like 'the meeting'."
                    ),
                },
                "thread_id": {
                    "type": "string",
                    "description": "Exact thread id, when you have one.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why it's closed, in David's terms (e.g. 'we had the meeting').",
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.thread_resolution import resolve_entity

        result = await resolve_entity(
            user_id,
            query=kwargs.get("query"),
            thread_id=kwargs.get("thread_id"),
            source="david_chat",
            reason=kwargs.get("reason"),
        )
        if result.get("error"):
            return ToolResult(success=False, message=result["error"])
        if not result["closed"]:
            return ToolResult(
                success=True, data=result,
                message="Nothing open matched that — there's nothing to close.",
            )
        titles = ", ".join(result["threads"][:3])
        extra = []
        if result["candidates"]:
            extra.append(f"{result['candidates']} queued message(s) dropped")
        if result["notifications"]:
            extra.append(f"{result['notifications']} notification(s) cleared")
        tail = f" ({'; '.join(extra)})" if extra else ""
        return ToolResult(
            success=True, data=result,
            message=f"Closed {result['closed']}: {titles}.{tail}",
        )


THREAD_TOOLS = [ResolveThreadTool()]
