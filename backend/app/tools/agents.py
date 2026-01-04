"""
Agent Handoff Tools - Tools for delegating tasks to background worker agents
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class HandoffToAgentsTool(BaseTool):
    """Hand off a research or analysis task to background worker agents"""

    name = "handoff_to_agents"
    description = """Hand off a research or analysis task to background worker agents.
    Use this when the user wants you to research something in the background,
    look into a topic thoroughly, compare options, or when they explicitly say
    'have your agents look into this', 'research this in the background',
    'look into this for me', or similar phrases.

    The agents will:
    - Search the web for real-time information
    - Read and analyze web pages
    - Access the user's notes and memories (read-only)
    - Compile a comprehensive report
    - Save results to the Agent Workspace folder
    - Notify the user when complete

    Best for: Research tasks, comparing products/options, learning about topics,
    gathering information that requires multiple sources."""

    parameters = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "A clear description of the research task or question to investigate. Be specific about what you want to learn."
            },
            "task_type": {
                "type": "string",
                "description": "Type of task: 'research' for web research, 'analysis' for analyzing user data",
                "enum": ["research", "analysis"],
                "default": "research"
            }
        },
        "required": ["task_description"]
    }

    async def execute(self, user_id: str, parameters: Dict[str, Any]) -> ToolResult:
        """Execute the handoff to background agents"""
        task_description = parameters.get("task_description", "")
        task_type = parameters.get("task_type", "research")

        if not task_description:
            return ToolResult(
                success=False,
                message="No task description provided",
                data=None
            )

        try:
            from app.services.background_task_service import background_task_service
            from app.main_simple import SessionLocal

            logger.info(f"Handing off task to agents: {task_description[:100]}...")

            # Create the background task
            db = SessionLocal()
            try:
                task = await background_task_service.create_task(
                    db=db,
                    user_id=str(user_id),
                    query=task_description,
                    task_type=task_type
                )

                # Start the task in background (fire and forget)
                asyncio.create_task(self._run_task_with_new_session(task.id))

                return ToolResult(
                    success=True,
                    message=f"Task handed off to agents successfully. Task ID: {task.id}",
                    data={
                        "task_id": task.id,
                        "status": "running",
                        "task_description": task_description[:200],
                        "note": "I'll notify you when the research is complete. Results will be saved to your Agent Workspace folder."
                    }
                )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error handing off to agents: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to hand off task: {str(e)}",
                data=None
            )

    async def _run_task_with_new_session(self, task_id: str):
        """Run the background task with a fresh database session"""
        try:
            from app.services.background_task_service import background_task_service
            from app.main_simple import SessionLocal

            db = SessionLocal()
            try:
                await background_task_service.run_task(db, task_id)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Background task {task_id} failed: {e}")


class GetBackgroundTasksTool(BaseTool):
    """Get status of active and recent background tasks"""

    name = "get_background_tasks"
    description = """Check the status of background tasks that agents are working on.
    Shows active tasks currently running and recently completed tasks.
    Use this when the user asks about their background tasks, agent work,
    or wants to know what research is pending/complete."""

    parameters = {
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

    async def execute(self, user_id: str, parameters: Dict[str, Any]) -> ToolResult:
        """Get background task status"""
        include_completed = parameters.get("include_completed", True)
        limit = parameters.get("limit", 5)

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
    HandoffToAgentsTool,
    GetBackgroundTasksTool
]
