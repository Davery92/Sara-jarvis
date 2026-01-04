"""
Machine Registry Models
Track registered machines for shadow mode with activity detection
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, JSON, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class Machine(Base):
    """Registered machine for shadow agent"""
    __tablename__ = "machine"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(String, unique=True, nullable=False)  # Unique agent identifier

    # Machine info
    hostname = Column(String, nullable=True)
    platform = Column(String, nullable=True)  # windows, darwin, linux
    os_version = Column(String, nullable=True)

    # Activity tracking
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    activity_level = Column(String, default="idle")  # idle, low, medium, high
    is_online = Column(Boolean, default=False)

    # Agent capabilities
    capabilities = Column(JSON, default=list)  # ["screenshot", "clipboard", "terminal", "file_access"]
    agent_version = Column(String, nullable=True)

    # Configuration
    screenshot_enabled = Column(Boolean, default=True)
    screenshot_interval_seconds = Column(Integer, default=30)
    clipboard_enabled = Column(Boolean, default=True)
    terminal_enabled = Column(Boolean, default=True)
    file_access_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")


class ShadowScreenshot(Base):
    """Screenshot captured during shadow session"""
    __tablename__ = "shadow_screenshot"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("shadow_session.id", ondelete="CASCADE"), nullable=False)

    # Storage
    minio_key = Column(String, nullable=False)  # Object storage key
    file_size_bytes = Column(Integer, nullable=True)

    # Context
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    window_title = Column(String, nullable=True)
    app_name = Column(String, nullable=True)
    image_hash = Column(String, nullable=True)  # For change detection

    # Privacy
    was_blurred = Column(Boolean, default=False)
    blur_reason = Column(String, nullable=True)  # "password_manager", "sensitive_url", etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("ShadowSession", backref="screenshots")
