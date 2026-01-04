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


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    all_day: Optional[bool] = None
    reminder_minutes: Optional[int] = None
    is_completed: Optional[bool] = None


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


class IOSCalendarSyncResponse(BaseModel):
    synced: int
    errors: int
