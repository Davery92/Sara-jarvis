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
    friendly_name = Column(String, nullable=True)  # User-defined name like "David's MacBook"
    platform = Column(String, nullable=True)  # windows, darwin, linux
    os_version = Column(String, nullable=True)

    # Activity tracking
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    activity_level = Column(String, default="idle")  # idle, low, medium, high
    is_online = Column(Boolean, default=False)

    # Activity metrics (updated with each heartbeat)
    keyboard_events_total = Column(Integer, default=0)
    mouse_events_total = Column(Integer, default=0)
    keyboard_events_recent = Column(Integer, default=0)  # Events in last heartbeat period
    mouse_events_recent = Column(Integer, default=0)  # Events in last heartbeat period
    active_window = Column(String, nullable=True)  # Current active window title
    active_app = Column(String, nullable=True)  # Current active application

    # Agent capabilities
    capabilities = Column(JSON, default=list)  # ["screenshot", "clipboard", "terminal", "file_access"]
    agent_version = Column(String, nullable=True)

    # Configuration
    screenshot_enabled = Column(Boolean, default=True)
    screenshot_interval_seconds = Column(Integer, default=300)  # 5 minutes
    clipboard_enabled = Column(Boolean, default=True)
    terminal_enabled = Column(Boolean, default=True)
    file_access_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")


class ShadowSession(Base):
    """Active shadow session for a machine"""
    __tablename__ = "shadow_session"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = Column(String, ForeignKey("machine.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Session state
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)

    # Session metadata
    session_type = Column(String, default="standard")  # standard, focus, monitoring

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    machine = relationship("Machine", backref="sessions")
    user = relationship("User")


class ShadowScreenshot(Base):
    """Screenshot captured during shadow session"""
    __tablename__ = "shadow_screenshot"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("shadow_session.id", ondelete="CASCADE"), nullable=True)

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
