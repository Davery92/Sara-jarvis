"""Calendar event model (main_simple.py table schema)."""
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class CalendarEvent(Base):
    """Calendar events with iOS sync support."""
    __tablename__ = "calendar_event"
    __table_args__ = {'extend_existing': True}

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
