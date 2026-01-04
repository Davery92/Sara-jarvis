"""
Project Tracker Tools
Allows Sara to query and manage development projects, tasks, and track progress.
"""

from typing import Dict, Any, Optional, List
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class GetProjectStateTool(BaseTool):
    """Tool for getting the current state of a project"""

    @property
    def name(self) -> str:
        return "get_project_state"

    @property
    def description(self) -> str:
        return """Get the current state of a software development project, including task counts, open bugs, and recent activity.

Use this when the user asks about a project's status, state, or progress.
Trigger phrases: "what's the state of [project]", "how's [project] doing", "status of [project]", "what's happening with [project]"

If no project name is provided, returns a summary across all projects."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name or prefix of the project (e.g., 'Risk Ninja' or 'RN'). Leave empty for all projects."
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get project state"""
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            response = service.format_project_state(user_id, project_name)

            return ToolResult(
                success=True,
                message=response,
                data={"project_name": project_name}
            )

        except Exception as e:
            logger.error(f"Failed to get project state: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get project state: {str(e)}"
            )
        finally:
            db.close()


class GetTaskDetailTool(BaseTool):
    """Tool for getting details about a specific task"""

    @property
    def name(self) -> str:
        return "get_task_detail"

    @property
    def description(self) -> str:
        return """Get details about a specific task by its tag (e.g., RN-42, SARA-17).

Use this when the user asks about a specific task.
Trigger phrases: "what's RN-42 about", "tell me about SARA-17", "status of RN-42"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_tag": {
                    "type": "string",
                    "description": "The task tag (e.g., 'RN-42', 'SARA-17')"
                }
            },
            "required": ["task_tag"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get task details"""
        task_tag = kwargs.get("task_tag", "")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            task = service.get_task_by_tag(user_id, task_tag)

            if not task:
                return ToolResult(
                    success=False,
                    message=f"Task '{task_tag}' not found."
                )

            response = service.format_task_detail(task)

            return ToolResult(
                success=True,
                message=response,
                data={"task_id": task.id, "task_tag": task_tag}
            )

        except Exception as e:
            logger.error(f"Failed to get task detail: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get task details: {str(e)}"
            )
        finally:
            db.close()


class ListTasksByStatusTool(BaseTool):
    """Tool for listing tasks by status"""

    @property
    def name(self) -> str:
        return "list_tasks_by_status"

    @property
    def description(self) -> str:
        return """List tasks filtered by status (backlog, in_progress, in_qa, completed).

Use this when the user asks about tasks in a particular status.
Trigger phrases: "what's in my backlog", "what tasks are in progress", "what's in QA", "what did I complete"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["backlog", "in_progress", "in_qa", "completed"],
                    "description": "The status to filter by"
                },
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                }
            },
            "required": ["status"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List tasks by status"""
        status = kwargs.get("status")
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            # Get project ID if name provided
            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            tasks = service.get_tasks_by_status(user_id, project_id, status)

            status_label = status.replace("_", " ").title()
            response = service.format_task_list(tasks, f"{status_label} Tasks")

            return ToolResult(
                success=True,
                message=response,
                data={"count": len(tasks), "status": status}
            )

        except Exception as e:
            logger.error(f"Failed to list tasks: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to list tasks: {str(e)}"
            )
        finally:
            db.close()


class GetOpenBugsTool(BaseTool):
    """Tool for listing open bugs"""

    @property
    def name(self) -> str:
        return "get_open_bugs"

    @property
    def description(self) -> str:
        return """Get all open bugs (not yet completed) across projects.

Use this when the user asks about bugs.
Trigger phrases: "how many open bugs", "what bugs do I have", "show me the bugs"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get open bugs"""
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            bugs = service.get_open_bugs(user_id, project_id)
            response = service.format_task_list(bugs, "Open Bugs")

            return ToolResult(
                success=True,
                message=response,
                data={"count": len(bugs)}
            )

        except Exception as e:
            logger.error(f"Failed to get bugs: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get bugs: {str(e)}"
            )
        finally:
            db.close()


class GetShippedThisWeekTool(BaseTool):
    """Tool for getting tasks completed this week"""

    @property
    def name(self) -> str:
        return "get_shipped_this_week"

    @property
    def description(self) -> str:
        return """Get tasks that were completed this week.

Use this when the user asks about what was shipped, completed, or finished recently.
Trigger phrases: "what did I ship this week", "what was completed", "what did I finish"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get shipped tasks"""
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            tasks = service.get_shipped_this_week(user_id, project_id)
            response = service.format_task_list(tasks, "Shipped This Week")

            return ToolResult(
                success=True,
                message=response,
                data={"count": len(tasks)}
            )

        except Exception as e:
            logger.error(f"Failed to get shipped tasks: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get shipped tasks: {str(e)}"
            )
        finally:
            db.close()


class GetRecentCommitsTool(BaseTool):
    """Tool for getting recent commits"""

    @property
    def name(self) -> str:
        return "get_recent_commits"

    @property
    def description(self) -> str:
        return """Get recent commits from GitHub.

Use this when the user asks about recent commits or git activity.
Trigger phrases: "show me recent commits", "what commits", "git activity"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of commits to return (default: 10)",
                    "default": 10
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get recent commits"""
        project_name = kwargs.get("project_name")
        limit = kwargs.get("limit", 10)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            commits = service.get_recent_commits(user_id, project_id, limit)
            response = service.format_commits_list(commits)

            return ToolResult(
                success=True,
                message=response,
                data={"count": len(commits)}
            )

        except Exception as e:
            logger.error(f"Failed to get commits: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get commits: {str(e)}"
            )
        finally:
            db.close()


class SuggestNextTaskTool(BaseTool):
    """Tool for suggesting what to work on next"""

    @property
    def name(self) -> str:
        return "suggest_next_task"

    @property
    def description(self) -> str:
        return """Suggest the next task to work on based on priority, bugs, and backlog age.

Use this when the user asks for a recommendation on what to work on.
Trigger phrases: "what should I work on next", "what's next", "suggest a task"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Suggest next task"""
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            task = service.suggest_next_task(user_id, project_id)

            if not task:
                return ToolResult(
                    success=True,
                    message="Your backlog is empty! Time to add some tasks."
                )

            response = f"I suggest working on:\n\n{service.format_task_detail(task)}"

            return ToolResult(
                success=True,
                message=response,
                data={"task_id": task.id}
            )

        except Exception as e:
            logger.error(f"Failed to suggest task: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to suggest task: {str(e)}"
            )
        finally:
            db.close()


class GetWeeklyVelocityTool(BaseTool):
    """Tool for getting weekly velocity metrics"""

    @property
    def name(self) -> str:
        return "get_weekly_velocity"

    @property
    def description(self) -> str:
        return """Get weekly velocity metrics including commits and completed tasks.

Use this when the user asks about their velocity, productivity, or activity level.
Trigger phrases: "what's my velocity", "how productive was I", "activity this week"."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project name to filter by"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get velocity metrics"""
        project_name = kwargs.get("project_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            from app.services.project_tracker_service import ProjectTrackerService
            service = ProjectTrackerService(db)

            project_id = None
            if project_name:
                project = service.get_project_by_name(user_id, project_name)
                if not project:
                    project = service.get_project_by_prefix(user_id, project_name)
                if project:
                    project_id = project.id

            velocity = service.get_weekly_velocity(user_id, project_id)

            response = f"""**This Week's Velocity**
- Commits: {velocity['commits']}
- Tasks Completed: {velocity['tasks_completed']}
- Average: {velocity['commits_per_day']} commits/day"""

            return ToolResult(
                success=True,
                message=response,
                data=velocity
            )

        except Exception as e:
            logger.error(f"Failed to get velocity: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to get velocity: {str(e)}"
            )
        finally:
            db.close()


# Register all project tools
PROJECT_TOOLS = [
    GetProjectStateTool(),
    GetTaskDetailTool(),
    ListTasksByStatusTool(),
    GetOpenBugsTool(),
    GetShippedThisWeekTool(),
    GetRecentCommitsTool(),
    SuggestNextTaskTool(),
    GetWeeklyVelocityTool(),
]
