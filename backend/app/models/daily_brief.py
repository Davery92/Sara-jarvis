"""
Daily Brief Model - For caching and managing daily briefings

This model stores generated daily briefs with sections and caching metadata.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Date, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class DailyBrief(Base):
    __tablename__ = "daily_briefs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    
    # Brief Content
    brief_date = Column(Date, nullable=False)  # Date this brief is for
    sections = Column(JSONB, default=lambda: [])  # [{id, title, items: [...]}]
    
    # Generation Metadata
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    generation_duration_ms = Column(Integer)  # How long it took to generate
    
    # Content Sources
    calendar_events_count = Column(Integer, default=0)
    reminders_count = Column(Integer, default=0)
    insights_count = Column(Integer, default=0)
    dream_highlights_count = Column(Integer, default=0)
    
    # Caching
    cache_key = Column(String(100))  # Redis cache key
    cache_expires_at = Column(DateTime(timezone=True))
    
    # User Interaction
    viewed_at = Column(DateTime(timezone=True), nullable=True)
    pinned_items = Column(JSONB, default=list)  # Items user pinned as reminders
    
    def __repr__(self):
        return f"<DailyBrief(id={self.id}, date={self.brief_date}, sections={len(self.sections or [])})"
    
    @property
    def is_today(self) -> bool:
        """Check if this brief is for today"""
        from datetime import date
        return self.brief_date == date.today()
    
    @property
    def total_items(self) -> int:
        """Count total items across all sections"""
        if not self.sections:
            return 0
        return sum(len(section.get('items', [])) for section in self.sections)