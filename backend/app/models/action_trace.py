"""SQLAlchemy model for autonomy_action_trace table."""

from sqlalchemy import Column, String, Integer, SmallInteger, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class ActionTrace(Base):
    __tablename__ = "autonomy_action_trace"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    run_uuid = Column(UUID(as_uuid=True), index=True)
    run_id = Column(Integer, ForeignKey("agent_run_log.id"), nullable=True)
    user_id = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False, default="unified_agent")
    action_name = Column(String(255), nullable=False)
    action_args = Column(JSONB)
    risk_tier = Column(SmallInteger, nullable=False, default=0)
    decision = Column(String(20), nullable=False, default="allow")
    decision_reason = Column(Text)
    simulation = Column(JSONB)
    result = Column(JSONB)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text)
    step_index = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(255), unique=True, nullable=True)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
