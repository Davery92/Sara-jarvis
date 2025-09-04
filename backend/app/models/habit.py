from sqlalchemy import Column, String, Integer, DateTime, Text, Float
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class Habit(Base):
    __tablename__ = "habits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    target_numeric = Column(Float, nullable=True)
    unit = Column(Text, nullable=True)
    rrule = Column(Text, nullable=False)
    weekly_minimum = Column(Integer, nullable=True)
    monthly_minimum = Column(Integer, nullable=True)
    windows = Column(Text, nullable=True)
    checklist_mode = Column(String, nullable=True)
    checklist_threshold = Column(Float, nullable=True)
    grace_days = Column(Integer, nullable=True)
    retro_hours = Column(Integer, nullable=True)
    paused = Column(Integer, nullable=True)
    pause_from = Column(DateTime, nullable=True)
    pause_to = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<Habit(title='{self.title}', type='{self.type}')>"


class HabitInstance(Base):
    __tablename__ = "habit_instances"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    habit_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    window = Column(Text, nullable=True)
    expected = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    progress = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<HabitInstance(habit_id='{self.habit_id}', status='{self.status}')>"