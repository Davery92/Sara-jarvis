from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from app.db.base import Base
from sqlalchemy.orm import Session
from sqlalchemy import and_, Column, String, Text, DateTime, Boolean, Integer
from sqlalchemy.sql import func
from datetime import datetime, timezone, date, time
import uuid


# Define CalendarEvent model here to match the calendar_event table
# This avoids circular import with main_simple.py
# Use extend_existing to avoid conflict with model defined in main_simple.py
class CalendarEvent(Base):
    """Model matching calendar_event table used by iOS calendar sync"""
    __tablename__ = "calendar_event"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    location = Column(String, default="")
    all_day = Column(Boolean, default=False)
    reminder_minutes = Column(Integer)
    is_completed = Column(Boolean, default=False)
    # iOS calendar sync fields
    source = Column(String, default="sara")  # 'sara' or 'ios_calendar'
    ios_event_id = Column(String, nullable=True)
    ios_calendar_id = Column(String, nullable=True)
    ios_calendar_name = Column(String, nullable=True)
    read_only = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


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
            
            # Query events from calendar_event table (includes iOS synced events)
            events = db.query(CalendarEvent).filter(
                CalendarEvent.user_id == user_id,
                and_(
                    CalendarEvent.start_time <= end_datetime,
                    CalendarEvent.end_time >= start_datetime
                )
            ).order_by(CalendarEvent.start_time).limit(limit).all()

            event_list = []
            for event in events:
                event_data = {
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": event.start_time.isoformat(),
                    "ends_at": event.end_time.isoformat(),
                    "location": event.location or "",
                    "description": event.description or "",
                    "created_at": event.created_at.isoformat(),
                    "updated_at": event.updated_at.isoformat()
                }
                # Include source info for iOS events
                if hasattr(event, 'source') and event.source == 'ios_calendar':
                    event_data["source"] = "ios_calendar"
                    event_data["ios_calendar_name"] = getattr(event, 'ios_calendar_name', None)
                event_list.append(event_data)
            
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
            
            # Create event in calendar_event table
            event = CalendarEvent(
                user_id=user_id,
                title=title,
                start_time=starts_at,
                end_time=ends_at,
                location=location or "",
                description=description or "",
                source="sara"
            )

            db.add(event)
            db.commit()
            db.refresh(event)

            return ToolResult(
                success=True,
                data={
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": event.start_time.isoformat(),
                    "ends_at": event.end_time.isoformat(),
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