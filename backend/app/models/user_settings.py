"""
User Settings Model
Stores user preferences including vision model, device settings, etc.
"""
from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class UserSettings(Base):
    """User preferences and settings"""
    __tablename__ = "user_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Vision settings
    vision_model = Column(String, default="qwen3-vl:latest")
    vision_endpoint = Column(String, default="http://10.185.1.8:11434")

    # Screenshot settings
    screenshot_enabled = Column(Boolean, default=True)
    screenshot_interval_seconds = Column(Integer, default=30)
    screenshot_blur_sensitive = Column(Boolean, default=True)  # Blur password fields, etc.

    # Desktop agent settings
    wake_word_enabled = Column(Boolean, default=True)
    activity_tracking_enabled = Column(Boolean, default=True)
    cross_device_commands_enabled = Column(Boolean, default=True)

    # Additional preferences (flexible JSON storage)
    preferences = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "vision_model": self.vision_model,
            "vision_endpoint": self.vision_endpoint,
            "screenshot_enabled": self.screenshot_enabled,
            "screenshot_interval_seconds": self.screenshot_interval_seconds,
            "screenshot_blur_sensitive": self.screenshot_blur_sensitive,
            "wake_word_enabled": self.wake_word_enabled,
            "activity_tracking_enabled": self.activity_tracking_enabled,
            "cross_device_commands_enabled": self.cross_device_commands_enabled,
            "preferences": self.preferences or {},
        }
