"""Daily briefing models."""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DailyBriefing(Base):
    """Daily briefings (morning/evening) with personalized insights."""
    __tablename__ = "daily_briefings"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    briefing_type = Column(String, nullable=False)  # "morning" or "evening"
    briefing_date = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    delivered = Column(Integer, default=0)
    read = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class BriefingSettings(Base):
    """User preferences for daily briefings."""
    __tablename__ = "briefing_settings"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, unique=True)
    morning_enabled = Column(Integer, default=1)
    morning_time = Column(String, default="07:00:00")
    evening_enabled = Column(Integer, default=1)
    evening_time = Column(String, default="21:00:00")
    include_recovery = Column(Integer, default=1)
    include_schedule = Column(Integer, default=1)
    include_goals = Column(Integer, default=1)
    include_suggestions = Column(Integer, default=1)
    include_workout_rec = Column(Integer, default=1)
    include_accomplishments = Column(Integer, default=1)
    include_insights = Column(Integer, default=1)
    include_reflection = Column(Integer, default=1)
    updated_at = Column(DateTime, server_default=func.now())
