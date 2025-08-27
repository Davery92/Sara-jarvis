from sqlalchemy import Column, String, DateTime, Boolean, Integer, Time, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class UserProfile(Base):
    """User profile created during GTKY interview"""
    __tablename__ = "user_profile"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    profile_data = Column(JSONB, nullable=False, default=dict)  # Goals, preferences, personality settings
    autonomy_level = Column(String(20), default="moderate")  # 'minimal', 'moderate', 'high'
    communication_style = Column(String(20), default="balanced")  # 'reserved', 'balanced', 'chatty'
    notification_channels = Column(JSONB, default=dict)  # ntfy topics, quiet hours, etc.
    gtky_completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship to user
    user = relationship("User", backref="profile")


class GTKYSession(Base):
    """Get-to-Know-You interview session tracking"""
    __tablename__ = "gtky_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    question_pack = Column(String(50), nullable=False)  # 'identity', 'preferences', 'goals'
    responses = Column(JSONB, nullable=False, default=dict)  # Question/answer pairs
    completed_at = Column(DateTime(timezone=True))
    session_metadata = Column(JSONB, default=dict)  # Progress, sprite mode, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship to user
    user = relationship("User", backref="gtky_sessions")


class DailyReflection(Base):
    """Daily reflection entries"""
    __tablename__ = "daily_reflections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    reflection_date = Column(Date, nullable=False)
    responses = Column(JSONB, nullable=False, default=dict)  # What went well, challenges, gratitude, etc.
    insights_generated = Column(JSONB, default=dict)  # Sara's generated insights for tomorrow
    mood_score = Column(Integer)  # Optional 1-10 scale
    reflection_duration_minutes = Column(Integer)  # How long reflection took
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship to user
    user = relationship("User", backref="daily_reflections")


class ReflectionSettings(Base):
    """User settings for nightly reflection routine"""
    __tablename__ = "reflection_settings"

    user_id = Column(String, ForeignKey("app_user.id"), primary_key=True)
    preferred_time = Column(Time, default="21:00")  # 9 PM default
    timezone = Column(String(50), default="UTC")
    enabled = Column(Boolean, default=True)
    quiet_hours = Column(JSONB, default=dict)  # Start/end times for no interruptions
    reminder_channels = Column(JSONB, default=dict)  # How to notify (sprite, ntfy, etc.)
    streak_count = Column(Integer, default=0)  # Consecutive days of reflection
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship to user
    user = relationship("User", backref="reflection_settings")


class PrivacySettings(Base):
    """Privacy and control settings"""
    __tablename__ = "privacy_settings"

    user_id = Column(String, ForeignKey("app_user.id"), primary_key=True)
    memory_retention_days = Column(Integer, default=365)
    share_reflections_with_ai = Column(Boolean, default=True)
    autonomous_level = Column(String(20), default="auto")  # 'disabled', 'ask-first', 'auto'
    data_categories = Column(JSONB, default=dict)  # What types of data to store/analyze
    export_enabled = Column(Boolean, default=True)
    analytics_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship to user
    user = relationship("User", backref="privacy_settings")


class UserActivityLog(Base):
    """Audit log for transparency"""
    __tablename__ = "user_activity_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    action_type = Column(String(50), nullable=False)  # 'gtky_completed', 'reflection_stored', etc.
    action_description = Column(Text)
    data_accessed = Column(JSONB, default=dict)  # What data was used
    ai_insights_generated = Column(JSONB, default=dict)  # What Sara learned/inferred
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship to user
    user = relationship("User", backref="activity_logs")