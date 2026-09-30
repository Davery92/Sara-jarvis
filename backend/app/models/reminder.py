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
    # R06 remainder (2026-09-26, extended round 4 2026-09-27): delivery
    # state machine for push dispatch of this occurrence. `notified_at` is
    # set ONLY on a terminal outcome (sent/missed/failed_permanent) —
    # never at claim time, so a crash between claiming and actually
    # sending cannot be mistaken for a real delivery. `delivery_status`:
    # claimed|sent|failed|failed_permanent|missed. `claimed_at` supports
    # claim-expiry reclaim (a crashed worker's stale claim becomes
    # reclaimable). `delivery_attempts`/`last_error` bound retries and aid
    # diagnostics. See app/tasks/inproc_schedulers.py notification_predispatch().
    notified_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(20), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

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
    # R06 remainder (2026-09-26, extended round 4 2026-09-27): see
    # Reminder's matching columns above for the full state-machine
    # rationale.
    notified_at = Column(DateTime(timezone=True), nullable=True)
    delivery_status = Column(String(20), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<Timer(title='{self.title}', duration={self.duration_minutes}m)>"
