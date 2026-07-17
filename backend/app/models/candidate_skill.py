"""CandidateSkill model — skills proposed by agents for review and promotion."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class CandidateSkill(Base):
    __tablename__ = "candidate_skill"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    instructions = Column(Text)
    contexts = Column(JSONB, default=list)
    priority = Column(Integer, default=50)
    status = Column(String(50), default="pending", index=True)  # pending/testing/accepted/rejected
    source_mission_id = Column(String(36), nullable=True)
    source_task_id = Column(String(36), nullable=True)
    vm_artifacts = Column(JSONB, default=dict)
    review_notes = Column(Text, nullable=True)
    times_used = Column(Integer, default=0, nullable=False, server_default="0")
    times_succeeded = Column(Integer, default=0, nullable=False, server_default="0")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)
