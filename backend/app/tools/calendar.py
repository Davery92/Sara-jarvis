from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from app.db.base import Base
from sqlalchemy.orm import Session
from sqlalchemy import and_, Column, String, Text, DateTime, Boolean, Integer
from sqlalchemy.sql import func
from datetime import datetime, timezone, date, time
from zoneinfo import ZoneInfo
import uuid

# User's local timezone - TODO: make this configurable per user
USER_TIMEZONE = ZoneInfo("America/New_York")


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
    # Recurrence fields
    rrule = Column(Text, nullable=True)  # RRULE string e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    recurring_event_id = Column(String, nullable=True)  # Parent event ID for occurrences
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


# Helper to build RRULE string from user-friendly parameters
def build_rrule(frequency: str, interval: int = 1, days: list = None,
                until: datetime = None, count: int = None) -> str:
    """
    Build an RRULE string from parameters.

    Args:
        frequency: DAILY, WEEKLY, MONTHLY, YEARLY
        interval: Every N periods (default 1)
        days: For WEEKLY, list of days like ['MO', 'TU', 'WE']
        until: End date for recurrence
        count: Number of occurrences
    """
    parts = [f"FREQ={frequency.upper()}"]

    if interval > 1:
        parts.append(f"INTERVAL={interval}")

    if days and frequency.upper() == "WEEKLY":
        parts.append(f"BYDAY={','.join(d.upper()[:2] for d in days)}")

    if until:
        parts.append(f"UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}")
    elif count:
        parts.append(f"COUNT={count}")

    return ";".join(parts)


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
            # Parse dates — use local time since DB stores naive local
            now = datetime.now(USER_TIMEZONE)
            
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
            
            # Convert to datetime ranges (naive local, matching DB convention)
            start_datetime = datetime.combine(start_date, time.min)
            end_datetime = datetime.combine(end_date, time.max)
            
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
                # Times are stored as naive local — tag with timezone for display
                local_start = event.start_time.replace(tzinfo=USER_TIMEZONE)
                local_end = event.end_time.replace(tzinfo=USER_TIMEZONE)

                event_data = {
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": local_start.strftime("%Y-%m-%d %I:%M %p"),
                    "ends_at": local_end.strftime("%Y-%m-%d %I:%M %p"),
                    "starts_at_iso": local_start.isoformat(),
                    "ends_at_iso": local_end.isoformat(),
                    "location": event.location or "",
                    "description": event.description or "",
                    "created_at": event.created_at.isoformat(),
                    "updated_at": event.updated_at.isoformat()
                }
                # Include recurrence info
                if hasattr(event, 'rrule') and event.rrule:
                    event_data["rrule"] = event.rrule
                    event_data["is_recurring"] = True
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
                    "description": "Event start time (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00'). Times without timezone are assumed to be in user's local timezone (EST/EDT)."
                },
                "ends_at": {
                    "type": "string",
                    "description": "Event end time (ISO 8601 datetime format, e.g., '2024-01-15T15:30:00'). Times without timezone are assumed to be in user's local timezone (EST/EDT)."
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location"
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description"
                },
                "recurrence": {
                    "type": "string",
                    "description": "Optional recurrence frequency: 'daily', 'weekly', 'monthly', 'yearly', or 'weekdays' (Mon-Fri)"
                },
                "recurrence_interval": {
                    "type": "integer",
                    "description": "Repeat every N periods (default 1). E.g., 2 with weekly = every 2 weeks"
                },
                "recurrence_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For weekly recurrence, specific days: ['monday', 'wednesday', 'friday']"
                },
                "recurrence_until": {
                    "type": "string",
                    "description": "End date for recurrence (YYYY-MM-DD format)"
                },
                "recurrence_count": {
                    "type": "integer",
                    "description": "Number of occurrences (alternative to recurrence_until)"
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

        # Recurrence parameters
        recurrence = kwargs.get("recurrence")
        recurrence_interval = kwargs.get("recurrence_interval", 1)
        recurrence_days = kwargs.get("recurrence_days")
        recurrence_until_str = kwargs.get("recurrence_until")
        recurrence_count = kwargs.get("recurrence_count")
        
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
            # DB stores naive local times (same convention as iOS calendar sync).
            # If no timezone, treat as local. If timezone given, convert to local then strip tzinfo.
            try:
                starts_at = datetime.fromisoformat(starts_at_str.replace('Z', '+00:00'))
                if starts_at.tzinfo is not None:
                    # Has timezone — convert to local time
                    starts_at = starts_at.astimezone(USER_TIMEZONE).replace(tzinfo=None)
                # else: naive = already local, store as-is
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid starts_at format. Please use ISO 8601 format (e.g., '2024-01-15T14:30:00')"
                )

            try:
                ends_at = datetime.fromisoformat(ends_at_str.replace('Z', '+00:00'))
                if ends_at.tzinfo is not None:
                    # Has timezone — convert to local time
                    ends_at = ends_at.astimezone(USER_TIMEZONE).replace(tzinfo=None)
                # else: naive = already local, store as-is
            except ValueError:
                return ToolResult(
                    success=False,
                    message="Invalid ends_at format. Please use ISO 8601 format (e.g., '2024-01-15T15:30:00')"
                )
            
            # Validate times
            if ends_at <= starts_at:
                return ToolResult(
                    success=False,
                    message="End time must be after start time"
                )

            # Build RRULE if recurrence is specified
            rrule = None
            if recurrence:
                # Map user-friendly names to RRULE frequencies
                freq_map = {
                    "daily": "DAILY",
                    "weekly": "WEEKLY",
                    "monthly": "MONTHLY",
                    "yearly": "YEARLY",
                    "weekdays": "WEEKLY"  # Special case handled below
                }
                frequency = freq_map.get(recurrence.lower())
                if not frequency:
                    return ToolResult(
                        success=False,
                        message=f"Invalid recurrence: {recurrence}. Use: daily, weekly, monthly, yearly, or weekdays"
                    )

                # Handle weekdays special case
                days = recurrence_days
                if recurrence.lower() == "weekdays":
                    days = ["MO", "TU", "WE", "TH", "FR"]

                # Parse until date if provided
                until_date = None
                if recurrence_until_str:
                    try:
                        until_date = datetime.strptime(recurrence_until_str, "%Y-%m-%d")
                        until_date = until_date.replace(tzinfo=USER_TIMEZONE).astimezone(timezone.utc)
                    except ValueError:
                        return ToolResult(
                            success=False,
                            message="Invalid recurrence_until format. Use YYYY-MM-DD."
                        )

                rrule = build_rrule(
                    frequency=frequency,
                    interval=recurrence_interval,
                    days=days,
                    until=until_date,
                    count=recurrence_count
                )

            # Create event in calendar_event table
            event = CalendarEvent(
                user_id=user_id,
                title=title,
                start_time=starts_at,
                end_time=ends_at,
                location=location or "",
                description=description or "",
                source="sara",
                rrule=rrule
            )

            db.add(event)
            db.commit()
            db.refresh(event)

            # Times are stored as naive local — use directly for display
            local_start = event.start_time.replace(tzinfo=USER_TIMEZONE)
            local_end = event.end_time.replace(tzinfo=USER_TIMEZONE)

            # Build response data
            response_data = {
                "event_id": str(event.id),
                "title": event.title,
                "starts_at": local_start.strftime("%Y-%m-%d %I:%M %p %Z"),
                "ends_at": local_end.strftime("%Y-%m-%d %I:%M %p %Z"),
                "starts_at_iso": local_start.isoformat(),
                "ends_at_iso": local_end.isoformat(),
                "location": event.location,
                "description": event.description,
                "created_at": event.created_at.isoformat()
            }

            # Add recurrence info if present
            if rrule:
                response_data["recurrence"] = recurrence
                response_data["rrule"] = rrule

            # Build message
            base_msg = f"Created event: {title} on {local_start.strftime('%A, %B %d at %I:%M %p')}"
            if recurrence:
                recurrence_desc = {
                    "daily": "repeating daily",
                    "weekly": "repeating weekly",
                    "monthly": "repeating monthly",
                    "yearly": "repeating yearly",
                    "weekdays": "repeating on weekdays"
                }.get(recurrence.lower(), f"repeating {recurrence}")
                base_msg += f" ({recurrence_desc})"

            return ToolResult(
                success=True,
                data=response_data,
                message=base_msg
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create event: {str(e)}"
            )
        finally:
            db.close()


class CalendarSetRecurringTool(BaseTool):
    """Tool for making an existing calendar event recurring"""

    @property
    def name(self) -> str:
        return "calendar_set_recurring"

    @property
    def description(self) -> str:
        return "Make an existing calendar event recurring by adding a recurrence pattern."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The ID of the event to make recurring"
                },
                "recurrence": {
                    "type": "string",
                    "description": "Recurrence frequency: 'daily', 'weekly', 'monthly', 'yearly', or 'weekdays' (Mon-Fri)"
                },
                "recurrence_interval": {
                    "type": "integer",
                    "description": "Repeat every N periods (default 1). E.g., 2 with weekly = every 2 weeks"
                },
                "recurrence_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For weekly recurrence, specific days: ['monday', 'wednesday', 'friday']"
                },
                "recurrence_until": {
                    "type": "string",
                    "description": "End date for recurrence (YYYY-MM-DD format)"
                },
                "recurrence_count": {
                    "type": "integer",
                    "description": "Number of occurrences (alternative to recurrence_until)"
                }
            },
            "required": ["event_id", "recurrence"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Make an existing event recurring"""

        event_id = kwargs.get("event_id")
        recurrence = kwargs.get("recurrence")
        recurrence_interval = kwargs.get("recurrence_interval", 1)
        recurrence_days = kwargs.get("recurrence_days")
        recurrence_until_str = kwargs.get("recurrence_until")
        recurrence_count = kwargs.get("recurrence_count")

        if not event_id:
            return ToolResult(
                success=False,
                message="Event ID is required"
            )

        if not recurrence:
            return ToolResult(
                success=False,
                message="Recurrence pattern is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the event
            event = db.query(CalendarEvent).filter(
                CalendarEvent.id == event_id,
                CalendarEvent.user_id == user_id
            ).first()

            if not event:
                return ToolResult(
                    success=False,
                    message=f"Event not found with ID: {event_id}"
                )

            # Build RRULE
            freq_map = {
                "daily": "DAILY",
                "weekly": "WEEKLY",
                "monthly": "MONTHLY",
                "yearly": "YEARLY",
                "weekdays": "WEEKLY"
            }
            frequency = freq_map.get(recurrence.lower())
            if not frequency:
                return ToolResult(
                    success=False,
                    message=f"Invalid recurrence: {recurrence}. Use: daily, weekly, monthly, yearly, or weekdays"
                )

            # Handle weekdays special case
            days = recurrence_days
            if recurrence.lower() == "weekdays":
                days = ["MO", "TU", "WE", "TH", "FR"]

            # Parse until date if provided
            until_date = None
            if recurrence_until_str:
                try:
                    until_date = datetime.strptime(recurrence_until_str, "%Y-%m-%d")
                    until_date = until_date.replace(tzinfo=USER_TIMEZONE).astimezone(timezone.utc)
                except ValueError:
                    return ToolResult(
                        success=False,
                        message="Invalid recurrence_until format. Use YYYY-MM-DD."
                    )

            rrule = build_rrule(
                frequency=frequency,
                interval=recurrence_interval,
                days=days,
                until=until_date,
                count=recurrence_count
            )

            # Update the event
            event.rrule = rrule
            db.commit()
            db.refresh(event)

            # Times are stored as naive local — tag with timezone for display
            local_start = event.start_time.replace(tzinfo=USER_TIMEZONE)

            recurrence_desc = {
                "daily": "repeating daily",
                "weekly": "repeating weekly",
                "monthly": "repeating monthly",
                "yearly": "repeating yearly",
                "weekdays": "repeating on weekdays"
            }.get(recurrence.lower(), f"repeating {recurrence}")

            return ToolResult(
                success=True,
                data={
                    "event_id": str(event.id),
                    "title": event.title,
                    "starts_at": local_start.strftime("%Y-%m-%d %I:%M %p %Z"),
                    "recurrence": recurrence,
                    "rrule": rrule
                },
                message=f"Made '{event.title}' {recurrence_desc}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to update event: {str(e)}"
            )
        finally:
            db.close()