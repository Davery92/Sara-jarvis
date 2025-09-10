"""
Jarvis Inbox Model - Central notification and insight system

This model handles all proactive notifications from monitors, 
background tasks, and system insights.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum
import uuid


class InboxKind(str, enum.Enum):
    INSIGHT = "insight"
    ALERT = "alert"
    REMINDER = "reminder"
    SUGGESTION = "suggestion"


class InboxStatus(str, enum.Enum):
    NEW = "new"
    READ = "read"
    ARCHIVED = "archived"


class JarvisInbox(Base):
    __tablename__ = "jarvis_inbox"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id"), nullable=False)
    
    # Content
    kind = Column(Enum(InboxKind), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    source = Column(String(50))  # e.g., 'calendar_monitor', 'dream', 'research_task'
    payload = Column(JSONB, default=dict)  # Structured data for the inbox item
    
    # Metadata
    priority = Column(Integer, default=5)  # 1-10 scale
    status = Column(Enum(InboxStatus), default=InboxStatus.NEW, nullable=False)
    
    # Deduplication and batching
    dedupe_key = Column(String(100))  # For preventing duplicates
    batch_id = Column(String(36))  # UUID for batched items
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    read_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    # user = relationship("User", back_populates="inbox_items")
    
    def __repr__(self):
        return f"<JarvisInbox(id={self.id}, kind={self.kind}, title='{self.title[:30]}')>"


# TODO: Add to User model
# class User(Base):
#     # ... existing fields ...
#     inbox_items = relationship("JarvisInbox", back_populates="user")