"""SQLAlchemy models for autonomy_mission and autonomy_mission_step tables."""

from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class Mission(Base):
    __tablename__ = "autonomy_mission"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(String(255), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    source = Column(String(50), nullable=False, default="user")
    state = Column(String(20), nullable=False, default="pending")
    priority = Column(String(20), nullable=False, default="normal")
    total_steps = Column(Integer, nullable=False, default=0)
    completed_steps = Column(Integer, nullable=False, default=0)
    current_step_index = Column(Integer, nullable=False, default=0)
    requires_confirmation = Column(Boolean, nullable=False, default=False)
    confirmed_at = Column(DateTime(timezone=True))
    mission_metadata = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))


class MissionStep(Base):
    __tablename__ = "autonomy_mission_step"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    mission_id = Column(UUID(as_uuid=True), ForeignKey("autonomy_mission.id", ondelete="CASCADE"), nullable=False)
    step_index = Column(Integer, nullable=False)
    action_name = Column(String(255), nullable=False)
    action_args = Column(JSONB, default={})
    description = Column(Text)
    status = Column(String(20), nullable=False, default="pending")
    result = Column(JSONB)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
