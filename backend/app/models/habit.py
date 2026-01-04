"""Habit tracking models."""
from sqlalchemy import Column, String, Text, DateTime, Float, Integer, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Habit(Base):
    """Core habit definition with scheduling and configuration."""
    __tablename__ = "habits"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    type = Column(String, nullable=False)  # binary, quantitative, checklist, time
    target_numeric = Column(Float, nullable=True)
    unit = Column(Text, nullable=True)  # oz, min, reps, pages
    rrule = Column(Text, nullable=False)  # RRULE string for expected days
    weekly_minimum = Column(Integer, nullable=True)
    monthly_minimum = Column(Integer, nullable=True)
    windows = Column(Text, nullable=True)  # JSON: [{"name":"Morning","start":"05:00","end":"11:30"}]
    checklist_mode = Column(String, nullable=True)  # all, percent
    checklist_threshold = Column(Float, nullable=True)
    grace_days = Column(Integer, default=0)
    retro_hours = Column(Integer, default=24)
    paused = Column(Integer, default=0)
    pause_from = Column(DateTime, nullable=True)
    pause_to = Column(DateTime, nullable=True)
    vacation_from = Column(DateTime, nullable=True)
    vacation_to = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    current_streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    last_completed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    # Relationships
    user = relationship("User")
    items = relationship("HabitItem", back_populates="habit", cascade="all, delete-orphan")
    instances = relationship("HabitInstance", back_populates="habit", cascade="all, delete-orphan")
    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")
    streak = relationship("HabitStreak", back_populates="habit", uselist=False, cascade="all, delete-orphan")
    links = relationship("HabitLink", back_populates="habit", cascade="all, delete-orphan")


class HabitItem(Base):
    """Checklist items for checklist-type habits."""
    __tablename__ = "habit_items"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    label = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    habit = relationship("Habit", back_populates="items")


class HabitInstance(Base):
    """Materialized daily instances for fast UI queries."""
    __tablename__ = "habit_instances"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    date = Column(DateTime, nullable=False)
    window = Column(Text, nullable=True)
    expected = Column(Integer, default=1)
    status = Column(String, nullable=False, default='pending')  # pending, complete, skipped
    progress = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    # Relationships
    habit = relationship("Habit", back_populates="instances")


class HabitLog(Base):
    """Individual completion logs with source tracking."""
    __tablename__ = "habit_logs"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    instance_id = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime, nullable=False, server_default=func.now())
    source = Column(String, nullable=False)  # manual, voice, timer, calendar, ntfy, health
    payload = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    habit = relationship("Habit", back_populates="logs")


class HabitStreak(Base):
    """Streak tracking per habit."""
    __tablename__ = "habit_streaks"
    __table_args__ = {'extend_existing': True}

    habit_id = Column(String, ForeignKey("habits.id", ondelete="CASCADE"), primary_key=True)
    current_streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    last_completed = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now())

    # Relationships
    habit = relationship("Habit", back_populates="streak")


class HabitLink(Base):
    """Links to notes/concepts/documents for graph integration."""
    __tablename__ = "habit_links"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    target_type = Column(String, nullable=False)  # note, concept, document
    target_id = Column(String, nullable=False)
    meta = Column(Text, nullable=True)  # JSON metadata
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    habit = relationship("Habit", back_populates="links")
