"""Reminder and Timer models."""
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Reminder(Base):
    """User reminder with title, description, and scheduled time."""
    __tablename__ = "reminder"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    reminder_time = Column(DateTime(timezone=True), nullable=False)
    is_completed = Column(Boolean, default=False)
    event_id = Column(String, ForeignKey("calendar_event.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<Reminder(title='{self.title[:30]}...', reminder_time='{self.reminder_time}')>"


class Timer(Base):
    """User timer with duration and active status."""
    __tablename__ = "timer"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<Timer(title='{self.title}', duration={self.duration_minutes}m)>"
