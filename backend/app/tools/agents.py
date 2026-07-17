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
    Shows active tasks currently running and recently completed tasks.
    Use this when the user asks about their background tasks, agent work,
    or wants to know what research is pending/complete."""

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
            from app.services.background_task_service import background_task_service
            from app.main_simple import SessionLocal

            db = SessionLocal()
            try:
                tasks = await background_task_service.get_recent_tasks(
                    db=db,
                    user_id=str(user_id),
                    limit=limit,
                    include_active=True
                )

                if not tasks:
                    return ToolResult(
                        success=True,
                        message="No background tasks found",
                        data={"tasks": []}
                    )

                task_list = []
                for task in tasks:
                    task_info = {
                        "id": task.id,
                        "status": task.status,
                        "query": task.original_query[:100] + "..." if len(task.original_query) > 100 else task.original_query,
                        "created_at": task.created_at.isoformat() if task.created_at else None,
                        "completed_at": task.completed_at.isoformat() if task.completed_at else None
                    }

                    # Include result note link if completed
                    if task.status == "completed" and task.result_note_id:
                        task_info["result_note_id"] = task.result_note_id

                    task_list.append(task_info)

                active_count = sum(1 for t in tasks if t.status in ("pending", "running"))
                completed_count = sum(1 for t in tasks if t.status == "completed")

                return ToolResult(
                    success=True,
                    message=f"Found {active_count} active and {completed_count} completed tasks",
                    data={
                        "tasks": task_list,
                        "active_count": active_count,
                        "completed_count": completed_count
                    }
                )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting background tasks: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get background tasks: {str(e)}",
                data=None
            )


# List of all agent-related tools
AGENT_TOOLS = [
    GetBackgroundTasksTool
]
