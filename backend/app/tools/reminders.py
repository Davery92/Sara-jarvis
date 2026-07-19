from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.models.reminder import Reminder
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, date
import logging
import uuid

logger = logging.getLogger(__name__)


class RemindersCreateTool(BaseTool):
    """Tool for creating new reminders"""

    @property
    def name(self) -> str:
        return "reminders_create"

    @property
    def description(self) -> str:
        return "Create a new reminder with a title and due date/time. The reminder_time parameter should be an ISO 8601 datetime string."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The reminder title/message"
                },
                "description": {
                    "type": "string",
                    "description": "Optional longer description"
                },
                "reminder_time": {
                    "type": "string",
                    "description": "When the reminder should trigger (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')"
                },
                "confirm_time": {
                    "type": "boolean",
                    "description": "Set true only when David explicitly asked for this exact time, to override a schedule-conflict warning."
                }
            },
            "required": ["title", "reminder_time"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new reminder"""

        title = kwargs.get("title")
        description = kwargs.get("description", "")
        reminder_time_str = kwargs.get("reminder_time")

        if not title:
            return ToolResult(
                success=False,
                message="Reminder title is required"
            )

        if not reminder_time_str:
            return ToolResult(
                success=False,
                message="Reminder time is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Parse the reminder_time datetime
            try:
                reminder_time = datetime.fromisoformat(reminder_time_str.replace('Z', '+00:00'))
                if reminder_time.tzinfo is None:
                    reminder_time = reminder_time.replace(tzinfo=timezone.utc)
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid reminder_time format. Please use ISO 8601 format (e.g., '2024-01-15T14:30:00Z')"
                )

            # H3 (Brain Alignment): consult David's stated life facts before
            # committing a time on his behalf. A reminder that lands after he's
            # left for work or inside his gym block is flagged so the LLM
            # re-picks — unless it explicitly passes confirm_time=true (David
            # asked for that exact time).
            if not kwargs.get("confirm_time"):
                try:
                    from app.core.timezone import to_local
                    from app.services.life_facts import check_schedule_conflict, describe_day
                    from app.db.session import get_async_session_factory
                    local_when = to_local(reminder_time)
                    async with get_async_session_factory()() as _lf_db:
                        conflict = await check_schedule_conflict(_lf_db, str(user_id), local_when)
                        day_note = await describe_day(_lf_db, str(user_id), local_when.date()) if conflict else None
                    if conflict:
                        return ToolResult(
                            success=False,
                            data={"schedule_conflict": conflict, "day": day_note},
                            message=(
                                f"That time conflicts with a fixed part of David's day: {conflict} "
                                f"{('(' + day_note + ') ') if day_note else ''}"
                                "Pick a time that avoids it. If David explicitly asked for this exact "
                                "time, call again with confirm_time=true."
                            ),
                        )
                except Exception as e:
                    logger.debug(f"life_fact conflict check skipped: {e}")

            reminder = Reminder(
                user_id=user_id,
                title=title,
                description=description,
                reminder_time=reminder_time,
                is_completed=False,
            )

            db.add(reminder)
            db.commit()
            db.refresh(reminder)

            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "reminder_time": reminder.reminder_time.isoformat(),
                    "is_completed": reminder.is_completed,
                    "created_at": reminder.created_at.isoformat()
                },
                message=f"Created reminder: {title[:50]}{'...' if len(title) > 50 else ''}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create reminder: {str(e)}"
            )
        finally:
            db.close()


class RemindersListTool(BaseTool):
    """Tool for listing reminders"""

    @property
    def name(self) -> str:
        return "reminders_list"

    @property
    def description(self) -> str:
        return "List reminders for a specific day or all upcoming reminders. Can filter by completion status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional date to filter reminders (YYYY-MM-DD format). If not provided, shows all upcoming reminders."
                },
                "include_completed": {
                    "type": "boolean",
                    "description": "Include completed reminders (default: false)",
                    "default": False
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of reminders to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List reminders"""

        date_str = kwargs.get("date")
        include_completed = kwargs.get("include_completed", False)
        limit = kwargs.get("limit", 20)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = db.query(Reminder).filter(Reminder.user_id == user_id)

            if not include_completed:
                query = query.filter(Reminder.is_completed == False)

            # Filter by date if provided
            if date_str:
                try:
                    filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    start_of_day = datetime.combine(filter_date, datetime.min.time(), timezone.utc)
                    end_of_day = datetime.combine(filter_date, datetime.max.time(), timezone.utc)

                    query = query.filter(
                        and_(
                            Reminder.reminder_time >= start_of_day,
                            Reminder.reminder_time <= end_of_day
                        )
                    )
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid date format. Please use YYYY-MM-DD format."
                    )
            else:
                # Show upcoming reminders only
                if not include_completed:
                    query = query.filter(Reminder.reminder_time >= datetime.now(timezone.utc))

            reminders = query.order_by(Reminder.reminder_time).limit(limit).all()

            reminder_list = []
            for reminder in reminders:
                reminder_list.append({
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "description": reminder.description or "",
                    "reminder_time": reminder.reminder_time.isoformat(),
                    "is_completed": bool(reminder.is_completed),
                    "created_at": reminder.created_at.isoformat()
                })

            message = f"Found {len(reminder_list)} reminders"
            if date_str:
                message += f" for {date_str}"

            return ToolResult(
                success=True,
                data={
                    "reminders": reminder_list,
                    "date": date_str,
                    "total_found": len(reminder_list)
                },
                message=message
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list reminders: {str(e)}"
            )
        finally:
            db.close()


class RemindersCancelTool(BaseTool):
    """Tool for canceling/completing reminders"""

    @property
    def name(self) -> str:
        return "reminders_cancel"

    @property
    def description(self) -> str:
        return "Cancel or complete a reminder by ID. Marks it as completed."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The ID of the reminder to cancel/complete"
                }
            },
            "required": ["reminder_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Cancel a reminder by marking it completed"""

        reminder_id = kwargs.get("reminder_id")

        if not reminder_id:
            return ToolResult(
                success=False,
                message="Reminder ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id,
                Reminder.user_id == user_id
            ).first()

            if not reminder:
                return ToolResult(
                    success=False,
                    message="Reminder not found"
                )

            if reminder.is_completed:
                return ToolResult(
                    success=False,
                    message="Reminder is already completed"
                )

            reminder.is_completed = True
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "reminder_time": reminder.reminder_time.isoformat(),
                    "is_completed": True
                },
                message=f"Cancelled reminder: {reminder.title[:50]}{'...' if len(reminder.title) > 50 else ''}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to cancel reminder: {str(e)}"
            )
        finally:
            db.close()
