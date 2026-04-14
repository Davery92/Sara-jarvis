"""Calendar event schemas."""
from typing import Optional, List
from pydantic import BaseModel


class CalendarEventCreate(BaseModel):
    title: str
    description: str = ""
    start_time: str  # ISO format datetime string
    end_time: str    # ISO format datetime string
    location: Optional[str] = None
    all_day: Optional[bool] = False
    reminder_minutes: Optional[int] = None
    # Recurrence fields
    rrule: Optional[str] = None  # RRULE string e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    recurrence: Optional[str] = None  # Friendly: daily, weekly, monthly, yearly, weekdays


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    all_day: Optional[bool] = None
    reminder_minutes: Optional[int] = None
    is_completed: Optional[bool] = None
    # Recurrence fields
    rrule: Optional[str] = None  # RRULE string e.g. "FREQ=WEEKLY;BYDAY=MO,WE,FR"
    recurrence: Optional[str] = None  # Friendly: daily, weekly, monthly, yearly, weekdays


class CalendarEventResponse(BaseModel):
    id: str
    title: str
    description: str
    start_time: str
    end_time: str
    location: Optional[str] = None
    all_day: bool
    reminder_minutes: Optional[int] = None
    is_completed: bool
    # Recurrence fields
    rrule: Optional[str] = None
    is_recurring: bool = False
    # iOS calendar sync fields
    source: str = "sara"
    ios_event_id: Optional[str] = None
    ios_calendar_id: Optional[str] = None
    ios_calendar_name: Optional[str] = None
    read_only: bool = False
    created_at: str
    updated_at: str


# iOS Calendar Sync models
class IOSCalendarEventSync(BaseModel):
    ios_event_id: str
    ios_calendar_id: str
    ios_calendar_name: str
    title: str
    description: Optional[str] = None
    start_time: str
    end_time: str
    location: Optional[str] = None
    all_day: bool = False


class IOSCalendarSyncRequest(BaseModel):
    events: List[IOSCalendarEventSync]
    # Sync window — when provided, the backend reconciles deletions by removing
    # any iOS-sourced events inside this window (from the listed calendars) that
    # are NOT present in the payload. Optional for backwards compat.
    window_start: Optional[str] = None  # ISO datetime (UTC)
    window_end: Optional[str] = None    # ISO datetime (UTC)
    calendar_ids: Optional[List[str]] = None  # iOS calendar IDs included in this sync


class IOSCalendarSyncResponse(BaseModel):
    synced: int
    errors: int
    deleted: int = 0
