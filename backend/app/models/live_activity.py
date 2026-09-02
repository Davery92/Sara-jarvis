"""ActivityKit update-token registrations for server-driven Live Activities."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import Base


class LiveActivityRegistration(Base):
    __tablename__ = "live_activity_registration"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    activity_id = Column(String(255), nullable=False)
    logical_id = Column(String(255), nullable=False)
    kind = Column(String(32), nullable=False)
    push_token = Column(Text, nullable=False)
    device_name = Column(String(255), nullable=True)
    environment = Column(String(16), nullable=False, default="production")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", name="uq_live_activity_user_activity"),
        Index("ix_live_activity_user_active", "user_id", "is_active", "kind"),
        Index("ix_live_activity_logical", "user_id", "logical_id", "is_active"),
    )
