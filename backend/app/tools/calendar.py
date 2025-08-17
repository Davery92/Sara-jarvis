from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.models.calendar import Event
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timezone, date, time
import uuid


class CalendarListTool(BaseTool):
    """Tool for listing calendar events"""
    
    @property
    def name(self) -> str:
        return "calendar_list"
    
    @property
    def description(self) -> str:
        return "List calendar events for a date range. If no dates are provided, shows events for the current week."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date for event listing (YYYY-MM-DD format). Defaults to today."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for event listing (YYYY-MM-DD format). Defaults to 7 days from start_date."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 50)",
                    "default": 50
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List calendar events"""
        
        start_date_str = kwargs.get("start_date")
        end_date_str = kwargs.get("end_date")
        limit = kwargs.get("limit", 50)
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Parse dates
            now = datetime.now(timezone.utc)
            
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid start_date format. Please use YYYY-MM-DD format."
                    )
            else:
                start_date = now.date()
            
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid end_date format. Please use YYYY-MM-DD format."
                    )
            else:
                # Default to 7 days from start_date
                from datetime import timedelta
                end_date = start_date + timedelta(days=7)
            
            # Convert to datetime ranges
            start_datetime = datetime.combine(start_date, time.min, timezone.utc)
            end_datetime = datetime.combine(end_date, time.max, timezone.utc)
            
            # Query events
            events = db.query(Event).filter(
                Event.user_id == user_id,
                and_(
                    Event.starts_at <= end_datetime,
                    Event.ends_at >= start_datetime
                )
            ).order_by(Event.starts_at).limit(limit).all()
            
            event_list = []
            for event in events:
                event_list.append({
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": event.starts_at.isoformat(),
                    "ends_at": event.ends_at.isoformat(),
                    "location": event.location,
                    "description": event.description,
                    "created_at": event.created_at.isoformat(),
                    "updated_at": event.updated_at.isoformat()
                })
            
            return ToolResult(
                success=True,
                data={
                    "events": event_list,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "total_found": len(event_list)
                },
                message=f"Found {len(event_list)} events from {start_date} to {end_date}"
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list events: {str(e)}"
            )
        finally:
            db.close()


class CalendarCreateTool(BaseTool):
    """Tool for creating calendar events"""
    
    @property
    def name(self) -> str:
        return "calendar_create"
    
    @property
    def description(self) -> str:
        return "Create a new calendar event with title, start/end times, and optional location and description."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The event title"
                },
                "starts_at": {
                    "type": "string",
                    "description": "Event start time (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')"
                },
                "ends_at": {
                    "type": "string",
                    "description": "Event end time (ISO 8601 datetime format, e.g., '2024-01-15T15:30:00Z')"
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location"
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description"
                }
            },
            "required": ["title", "starts_at", "ends_at"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new calendar event"""
        
        title = kwargs.get("title")
        starts_at_str = kwargs.get("starts_at")
        ends_at_str = kwargs.get("ends_at")
        location = kwargs.get("location", "")
        description = kwargs.get("description", "")
        
        if not title:
            return ToolResult(
                success=False,
                message="Event title is required"
            )
        
        if not starts_at_str or not ends_at_str:
            return ToolResult(
                success=False,
                message="Both start and end times are required"
            )
        
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            # Parse the datetime strings
            try:
                starts_at = datetime.fromisoformat(starts_at_str.replace('Z', '+00:00'))
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=timezone.utc)
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid starts_at format. Please use ISO 8601 format (e.g., '2024-01-15T14:30:00Z')"
                )
            
            try:
                ends_at = datetime.fromisoformat(ends_at_str.replace('Z', '+00:00'))
                if ends_at.tzinfo is None:
                    ends_at = ends_at.replace(tzinfo=timezone.utc)
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid ends_at format. Please use ISO 8601 format (e.g., '2024-01-15T15:30:00Z')"
                )
            
            # Validate times
            if ends_at <= starts_at:
                return ToolResult(
                    success=False,
                    message="End time must be after start time"
                )
            
            # Create event
            event = Event(
                user_id=user_id,
                title=title,
                starts_at=starts_at,
                ends_at=ends_at,
                location=location,
                description=description
            )
            
            db.add(event)
            db.commit()
            db.refresh(event)
            
            return ToolResult(
                success=True,
                data={
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": event.starts_at.isoformat(),
                    "ends_at": event.ends_at.isoformat(),
                    "location": event.location,
                    "description": event.description,
                    "created_at": event.created_at.isoformat()
                },
                message=f"Created event: {title}"
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create event: {str(e)}"
            )
        finally:
            db.close()