"""Intelligence report, suggestion, and pattern models."""
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, JSON
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class IntelligenceReport(Base):
    """Periodic intelligence reports (weekly/monthly/quarterly)."""
    __tablename__ = "intelligence_reports"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    report_type = Column(String, nullable=False)  # weekly, monthly, quarterly
    report_date = Column(DateTime, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    full_content = Column(Text, nullable=True)
    key_insights = Column(Text, nullable=True)  # JSON array
    metrics = Column(Text, nullable=True)  # JSON object
    created_at = Column(DateTime, server_default=func.now())


class ProactiveSuggestion(Base):
    """AI-generated proactive suggestions based on patterns."""
    __tablename__ = "proactive_suggestion"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    suggestion_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    action_data = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    priority = Column(Integer, default=5)
    status = Column(String, default="pending")  # pending, accepted, dismissed
    expires_at = Column(DateTime(timezone=True), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    actioned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DetectedPattern(Base):
    """Automatically detected behavioral/temporal patterns."""
    __tablename__ = "detected_pattern"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    pattern_type = Column(String, nullable=False)  # temporal, behavioral, correlational, anomaly
    title = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    pattern_data = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    frequency = Column(String, nullable=True)  # daily, weekly, monthly
    data_points = Column(Integer, nullable=True)
    evidence = Column(Text, nullable=True)  # JSON array
    related_episodes = Column(Text, nullable=True)  # JSON array
    occurrences = Column(Integer, nullable=True, default=1)
    first_detected = Column(DateTime(timezone=True), server_default=func.now())
    last_detected = Column(DateTime(timezone=True), nullable=True)
    last_confirmed = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
