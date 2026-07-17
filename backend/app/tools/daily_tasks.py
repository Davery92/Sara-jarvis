"""AI tools for daily task management."""
from typing import Dict, Any
from datetime import date, datetime, timezone

from app.tools.base import BaseTool, ToolResult
from app.models.daily_task import DailyTask
from app.db.session import get_db
from sqlalchemy.orm import Session


class DailyTaskCreateTool(BaseTool):
    """Tool for creating a daily task."""

    @property
    def name(self) -> str:
        return "daily_task_create"

    @property
    def description(self) -> str:
        return "Create a task for today (or a specific date). Use this when the user wants to add something to their task list."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The task title"
                },
                "description": {
                    "type": "string",
                    "description": "Optional longer description of the task"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Task priority (default: normal)"
                },
                "task_date": {
                    "type": "string",
                    "description": "Date for the task in YYYY-MM-DD format (default: today)"
                }
            },
            "required": ["title"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        title = kwargs.get("title")
        if not title:
            return ToolResult(success=False, message="Task title is required")

        description = kwargs.get("description")
        priority = kwargs.get("priority", "normal")
        date_str = kwargs.get("task_date")

        task_date = date.today()
        if date_str:
            try:
                task_date = date.fromisoformat(date_str)
            except ValueError:
                return ToolResult(success=False, message="Invalid date format, use YYYY-MM-DD")

        if priority not in ("low", "normal", "high"):
            priority = "normal"

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            task = DailyTask(
                user_id=user_id,
                title=title,
                description=description,
                task_date=task_date,
                priority=priority,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            return ToolResult(
                success=True,
                data={
                    "task_id": task.id,
                    "title": task.title,
                    "task_date": str(task.task_date),
                    "priority": task.priority,
                },
                message=f"Created task: {title}"
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create task: {e}")
        finally:
            db.close()


class DailyTaskListTool(BaseTool):
    """Tool for listing today's tasks."""

    @property
    def name(self) -> str:
        return "daily_task_list"

    @property
    def description(self) -> str:
        return "List tasks for today or a specific date. Shows completion status and priority."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_date": {
                    "type": "string",
                    "description": "Date to list tasks for in YYYY-MM-DD format (default: today)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        date_str = kwargs.get("task_date")
        task_date = date.today()
        if date_str:
            try:
                task_date = date.fromisoformat(date_str)
            except ValueError:
                return ToolResult(success=False, message="Invalid date format, use YYYY-MM-DD")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            tasks = (
                db.query(DailyTask)
                .filter(DailyTask.user_id == user_id, DailyTask.task_date == task_date)
                .order_by(DailyTask.is_completed, DailyTask.priority.desc(), DailyTask.created_at)
                .all()
            )

            task_list = []
            for t in tasks:
                task_list.append({
                    "task_id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "priority": t.priority,
                    "is_completed": bool(t.is_completed),
                })

            completed = sum(1 for t in tasks if t.is_completed)
            total = len(tasks)

            return ToolResult(
                success=True,
                data={"tasks": task_list, "date": str(task_date), "completed": completed, "total": total},
                message=f"{completed}/{total} tasks completed for {task_date}"
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list tasks: {e}")
        finally:
            db.close()


class DailyTaskCompleteTool(BaseTool):
    """Tool for marking a task as done."""

    @property
    def name(self) -> str:
        return "daily_task_complete"

    @property
    def description(self) -> str:
        return "Mark a daily task as completed. Can match by ID or by title (partial match)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to complete"
                },
                "title": {
                    "type": "string",
                    "description": "Title of the task to complete (uses fuzzy match if no ID given)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        task_id = kwargs.get("task_id")
        title = kwargs.get("title")

        if not task_id and not title:
            return ToolResult(success=False, message="Provide either task_id or title")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            task = None
            if task_id:
                task = db.query(DailyTask).filter(
                    DailyTask.id == task_id, DailyTask.user_id == user_id
                ).first()
            elif title:
                # Try exact match first, then case-insensitive contains
                task = db.query(DailyTask).filter(
                    DailyTask.user_id == user_id,
                    DailyTask.task_date == date.today(),
                    DailyTask.is_completed == False,
                    DailyTask.title.ilike(f"%{title}%"),
                ).first()

            if not task:
                return ToolResult(success=False, message="Task not found")

            if task.is_completed:
                return ToolResult(success=True, message=f"Task '{task.title}' is already completed")

            task.is_completed = True
            task.completed_at = datetime.now(timezone.utc)
            db.commit()

            return ToolResult(
                success=True,
                data={"task_id": task.id, "title": task.title},
                message=f"Completed task: {task.title}"
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to complete task: {e}")
        finally:
            db.close()
