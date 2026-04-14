"""ACS Session Log — enhanced session tracking for v2."""

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSSessionLog(Base):
    __tablename__ = "acs_session_log"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    mode = Column(String(20), nullable=True)
    engagement_scores = Column(JSONB, default=list)
    avg_engagement = Column(Float, nullable=True)
    early_termination = Column(Boolean, default=False)
    turns_completed = Column(Integer, default=0)
    nodes_created = Column(Integer, default=0)
    nodes_updated = Column(Integer, default=0)
    edges_created = Column(Integer, default=0)
    notes_written = Column(Integer, default=0)
    self_model_updated = Column(Boolean, default=False)
    summary = Column(Text, nullable=True)
    next_session_intent = Column(Text, nullable=True)
    primary_topic = Column(String, nullable=True)
    primary_objective = Column(Text, nullable=True)
    expected_artifact = Column(Text, nullable=True)
    outcome_type = Column(String, nullable=True)
    artifact_summary = Column(Text, nullable=True)
    outbound_messages = Column(Integer, default=0)
    suppressed_messages = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Float, nullable=True)

    def __repr__(self):
        return f"<ACSSessionLog {self.id[:8]} mode={self.mode}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "mode": self.mode,
            "engagement_scores": self.engagement_scores,
            "avg_engagement": self.avg_engagement,
            "early_termination": self.early_termination,
            "turns_completed": self.turns_completed,
            "nodes_created": self.nodes_created,
            "nodes_updated": self.nodes_updated,
            "edges_created": self.edges_created,
            "notes_written": self.notes_written,
            "self_model_updated": self.self_model_updated,
            "summary": self.summary,
            "next_session_intent": self.next_session_intent,
            "primary_topic": self.primary_topic,
            "primary_objective": self.primary_objective,
            "expected_artifact": self.expected_artifact,
            "outcome_type": self.outcome_type,
            "artifact_summary": self.artifact_summary,
            "outbound_messages": self.outbound_messages,
            "suppressed_messages": self.suppressed_messages,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_minutes": self.duration_minutes,
        }
