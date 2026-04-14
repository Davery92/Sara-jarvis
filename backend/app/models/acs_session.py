"""ACS (Autonomous Cognition System) session tracking."""

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum
import uuid


class ACSState(str, enum.Enum):
    AUTONOMOUS = "autonomous"
    PAUSING = "pausing"
    CONVERSATIONAL = "conversational"
    COOLDOWN = "cooldown"


class ACSEndReason(str, enum.Enum):
    TIMEOUT = "timeout"
    CONVERSATION = "conversation"
    MANUAL = "manual"
    ERROR = "error"
    COMPLETED = "completed"


class ACSSession(Base):
    __tablename__ = "acs_session"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    vm_session_id = Column(String, nullable=True)
    model_id = Column(String, nullable=False, default="Qwen3.5-122B-A10B")
    state = Column(String, nullable=False, default="autonomous")
    started_at = Column(DateTime, server_default=func.now())
    paused_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    end_reason = Column(String, nullable=True)  # timeout|conversation|manual|error|completed
    turns_completed = Column(Integer, default=0)
    notes_created = Column(Integer, default=0)
    curiosities_explored = Column(Integer, default=0)
    token_usage = Column(JSONB, default={})
    context_summary = Column(Text, nullable=True)
    error_log = Column(Text, nullable=True)
    cognitive_mode = Column(String, nullable=True)
    engagement_score = Column(Float, nullable=True)

    def __repr__(self):
        return f"<ACSSession {self.id[:8]} state={self.state}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "vm_session_id": self.vm_session_id,
            "model_id": self.model_id,
            "state": self.state,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "end_reason": self.end_reason,
            "turns_completed": self.turns_completed,
            "notes_created": self.notes_created,
            "curiosities_explored": self.curiosities_explored,
            "token_usage": self.token_usage,
            "context_summary": self.context_summary,
            "error_log": self.error_log,
            "cognitive_mode": self.cognitive_mode,
            "engagement_score": self.engagement_score,
        }
