"""Research Plan and Research Message models for the research delegation system."""

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import enum
import uuid


class ResearchPlanStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STUCK = "stuck"
    COMPLETE = "complete"
    FAILED = "failed"


class ResearchMessageDirection(str, enum.Enum):
    AGENT_TO_SARA = "agent_to_sara"
    SARA_TO_AGENT = "sara_to_agent"


class ResearchMessageStatus(str, enum.Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    DISMISSED = "dismissed"


class ResearchPlan(Base):
    __tablename__ = "research_plan"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    objective = Column(Text, nullable=False)
    steps = Column(JSONB, nullable=False, default=[])
    status = Column(String, nullable=False, default="draft")
    created_by = Column(String, nullable=False, default="sara")
    current_step_index = Column(Integer, default=0)
    findings_summary = Column(Text, nullable=True)
    model_id = Column(String, nullable=True, default="Qwen3.5-27B")
    container_vmid = Column(Integer, nullable=True)
    total_tokens_used = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ResearchPlan {self.id[:8]} '{self.title}' status={self.status}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "objective": self.objective,
            "steps": self.steps,
            "status": self.status,
            "created_by": self.created_by,
            "current_step_index": self.current_step_index,
            "findings_summary": self.findings_summary,
            "model_id": self.model_id,
            "container_vmid": self.container_vmid,
            "total_tokens_used": self.total_tokens_used,
            "error_log": self.error_log,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ResearchMessage(Base):
    __tablename__ = "research_message"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)  # agent_to_sara | sara_to_agent
    content = Column(Text, nullable=False)
    step_index = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, server_default=func.now())
    answered_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ResearchMessage {self.id[:8]} {self.direction} status={self.status}>"

    def to_dict(self):
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "direction": self.direction,
            "content": self.content,
            "step_index": self.step_index,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }
