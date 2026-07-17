"""SQLAlchemy model for autonomy_policy_candidate table."""

from sqlalchemy import Column, String, Float, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class PolicyCandidate(Base):
    __tablename__ = "autonomy_policy_candidate"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(String(255), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    candidate_type = Column(String(50), nullable=False, default="standing_order")
    source = Column(String(50), nullable=False, default="dream")
    source_id = Column(String(255))
    status = Column(String(20), nullable=False, default="new")
    confidence = Column(Float, nullable=False, default=0.5)
    proposed_config = Column(JSONB, default={})
    dedupe_key = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at = Column(DateTime(timezone=True))
    decided_action = Column(String(20))
    result_id = Column(String(255))
