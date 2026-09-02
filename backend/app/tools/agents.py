"""
Agent inspection tools — observe background worker tasks.

NOTE: The old `handoff_to_agents` tool was removed in favor of:
- `create_research_plan` for chat-initiated research (David asks "look into X")
- `dispatch_agent_task` / `dispatch_and_monitor` for sandbox & internal-data work
"""

import logging
from typing import Dict, Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class GetBackgroundTasksTool(BaseTool):
    """Get status of active and recent background tasks"""

    @property
    def name(self) -> str:
        return "get_background_tasks"

    @property
    def description(self) -> str:
        return """Check the status of background tasks that agents are working on.
    Shows EVERYTHING Sara has dispatched — chat handoffs, agent/host dispatch,
    code mode, and research plans — active and recently completed.
    Use this when the user asks about their background tasks, agent work,
    or wants to know what research is pending/complete. This is the same feed
    the phone and web UI show, so what it says is what David sees."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_completed": {
                    "type": "boolean",
                    "description": "Include recently completed tasks (default: true)",
                    "default": True
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent tasks to return (default: 5)",
                    "default": 5
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get background task status"""
        include_completed = kwargs.get("include_completed", True)
        limit = kwargs.get("limit", 5)

        try:
            # Same function the web badge and the iOS pill read. Sara used to
            # query `background_task` alone here, which is blind to research
            # plans — that is how she reported "zero active tasks" while a plan
            # was on step 3 (2026-09-01 Salem incident). She can never again see
            # a different world than David.
            from app.services.agent_activity import ACTIVE_STATUSES, get_agent_activity
            from app.main_simple import SessionLocal

            db = SessionLocal()
            try:
                tasks = await get_agent_activity(
                    db,
                    str(user_id),
                    limit=limit,
                    include_active=True,
                )

                if not tasks:
                    return ToolResult(
                        success=True,
                        message="No background tasks found",
                        data={"tasks": []}
                    )

                task_list = []
                for task in tasks:
                    query = task.original_query or ""
                    task_info = {
                        "id": task.id,
                        "status": task.status,
                        "kind": task.task_type,
                        "query": query[:100] + "..." if len(query) > 100 else query,
                        "created_at": task.created_at,
                        "completed_at": task.completed_at,
                    }
                    if task.status_label:
                        task_info["progress"] = task.status_label
                    if task.error_message:
                        task_info["error"] = task.error_message[:300]

                    # Include result note link if completed
                    if task.status == "completed" and task.result_note_id:
                        task_info["result_note_id"] = task.result_note_id

                    task_list.append(task_info)

                active = [t for t in tasks if t.status in ACTIVE_STATUSES]
                completed_count = sum(1 for t in tasks if t.status == "completed")

                if active:
                    detail = "; ".join(
                        f"{t.task_type} {t.id[:8]} — {t.original_query[:60]}"
                        + (f" ({t.status_label})" if t.status_label else "")
                        for t in active
                    )
                    message = f"{len(active)} active: {detail}. {completed_count} recently completed."
                else:
                    message = f"Nothing running right now. {completed_count} recently completed."

                return ToolResult(
                    success=True,
                    message=message,
                    data={
                        "tasks": task_list,
                        "active_count": len(active),
                        "completed_count": completed_count
                    }
                )
            finally:
                db.close()

        except Exception as e:
            logger.error(
                "Error getting background tasks: %s: %s", type(e).__name__, e, exc_info=True
            )
            return ToolResult(
                success=False,
                message=f"Failed to get background tasks: {type(e).__name__}: {e}",
                data=None
            )


# List of all agent-related tools
AGENT_TOOLS = [
    GetBackgroundTasksTool
]
