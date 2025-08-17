from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.models.reminder import Reminder
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, date
import uuid


class RemindersCreateTool(BaseTool):
    """Tool for creating new reminders"""
    
    @property
    def name(self) -> str:
        return "reminders_create"
    
    @property
    def description(self) -> str:
        return "Create a new reminder with text and due date/time. The due_at parameter should be an ISO 8601 datetime string."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The reminder text/message"
                },
                "due_at": {
                    "type": "string",
                    "description": "When the reminder should trigger (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')"
                }
            },
            "required": ["text", "due_at"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new reminder"""
        
        text = kwargs.get("text")
        due_at_str = kwargs.get("due_at")
        
        if not text:
            return ToolResult(
                success=False,
                message="Reminder text is required"
            )
        
        if not due_at_str:
            return ToolResult(
                success=False,
                message="Due date/time is required"
            )
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Parse the due_at datetime
            try:
                due_at = datetime.fromisoformat(due_at_str.replace('Z', '+00:00'))
                # Ensure it's timezone-aware
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid due_at format. Please use ISO 8601 format (e.g., '2024-01-15T14:30:00Z')"
                )
            
            # Create reminder
            reminder = Reminder(
                user_id=user_id,
                text=text,
                due_at=due_at,
                status="scheduled"
            )
            
            db.add(reminder)
            db.commit()
            db.refresh(reminder)
            
            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "text": reminder.text,
                    "due_at": reminder.due_at.isoformat(),
                    "status": reminder.status,
                    "created_at": reminder.created_at.isoformat()
                },
                message=f"Created reminder: {text[:50]}{'...' if len(text) > 50 else ''}"
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
        return "List reminders for a specific day or all upcoming reminders. Can filter by status (scheduled, completed, cancelled)."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Optional date to filter reminders (YYYY-MM-DD format). If not provided, shows all upcoming reminders."
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (scheduled, completed, cancelled). Defaults to 'scheduled'.",
                    "default": "scheduled"
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
        status = kwargs.get("status", "scheduled")
        limit = kwargs.get("limit", 20)
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            query = db.query(Reminder).filter(
                Reminder.user_id == user_id,
                Reminder.status == status
            )
            
            # Filter by date if provided
            if date_str:
                try:
                    filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    start_of_day = datetime.combine(filter_date, datetime.min.time(), timezone.utc)
                    end_of_day = datetime.combine(filter_date, datetime.max.time(), timezone.utc)
                    
                    query = query.filter(
                        and_(
                            Reminder.due_at >= start_of_day,
                            Reminder.due_at <= end_of_day
                        )
                    )
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid date format. Please use YYYY-MM-DD format."
                    )
            else:
                # Show upcoming reminders only
                if status == "scheduled":
                    query = query.filter(Reminder.due_at >= datetime.now(timezone.utc))
            
            reminders = query.order_by(Reminder.due_at).limit(limit).all()
            
            reminder_list = []
            for reminder in reminders:
                reminder_list.append({
                    "reminder_id": str(reminder.id),
                    "text": reminder.text,
                    "due_at": reminder.due_at.isoformat(),
                    "status": reminder.status,
                    "created_at": reminder.created_at.isoformat()
                })
            
            message = f"Found {len(reminder_list)} {status} reminders"
            if date_str:
                message += f" for {date_str}"
            
            return ToolResult(
                success=True,
                data={
                    "reminders": reminder_list,
                    "status": status,
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
    """Tool for canceling reminders"""
    
    @property
    def name(self) -> str:
        return "reminders_cancel"
    
    @property
    def description(self) -> str:
        return "Cancel a reminder by ID. This sets the reminder status to 'cancelled'."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The ID of the reminder to cancel"
                }
            },
            "required": ["reminder_id"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Cancel a reminder"""
        
        reminder_id = kwargs.get("reminder_id")
        
        if not reminder_id:
            return ToolResult(
                success=False,
                message="Reminder ID is required"
            )
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Find the reminder
            reminder = db.query(Reminder).filter(
                Reminder.id == reminder_id,
                Reminder.user_id == user_id
            ).first()
            
            if not reminder:
                return ToolResult(
                    success=False,
                    message="Reminder not found"
                )
            
            if reminder.status == "cancelled":
                return ToolResult(
                    success=False,
                    message="Reminder is already cancelled"
                )
            
            # Cancel the reminder
            reminder.status = "cancelled"
            db.commit()
            
            return ToolResult(
                success=True,
                data={
                    "reminder_id": str(reminder.id),
                    "text": reminder.text,
                    "due_at": reminder.due_at.isoformat(),
                    "status": reminder.status
                },
                message=f"Cancelled reminder: {reminder.text[:50]}{'...' if len(reminder.text) > 50 else ''}"
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to cancel reminder: {str(e)}"
            )
        finally:
            db.close()