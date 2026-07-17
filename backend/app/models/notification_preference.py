"""Notification preference model — per-user category toggles and custom ban phrases."""
import uuid

from sqlalchemy import Column, String, Boolean, DateTime, JSON, Integer
from sqlalchemy.sql import func

from app.db.base import Base


class NotificationPreference(Base):
    """
    Per-user, per-category notification preferences.

    Enables dynamic control over which notification categories are allowed
    and optional custom ban phrases for fine-grained filtering.
    """
    __tablename__ = "notification_preference"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False)  # health, fitness, calendar, email, security, home, general
    enabled = Column(Boolean, default=True, nullable=False)
    custom_ban_phrases = Column(JSON, default=list)  # user-specified additional ban phrases
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
