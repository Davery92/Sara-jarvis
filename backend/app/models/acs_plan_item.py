"""ACS plan item — daily work items for Sara's autonomous cognition system."""

from sqlalchemy import Column, String, Text, DateTime, Date, Integer, Index
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSPlanItem(Base):
    __tablename__ = "acs_plan_item"
    __table_args__ = (
        Index("ix_acs_plan_item_user_date_status", "user_id", "plan_date", "status"),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    plan_date = Column(Date, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    success_criteria = Column(Text, nullable=True)
    priority = Column(Integer, default=50)  # 0-100, higher = more important
    status = Column(String, default="pending")  # pending|in_progress|completed|blocked|deferred|parked|cancelled
    source = Column(String, default="morning_plan")  # morning_plan|david_chat|directive|carryover
    source_ref = Column(String, nullable=True)  # task_id or directive_id that spawned this
    estimated_turns = Column(Integer, nullable=True)
    assigned_session_id = Column(String, nullable=True)  # which session is working on this
    result_summary = Column(Text, nullable=True)
    blocker_reason = Column(Text, nullable=True)
    depends_on = Column(String, nullable=True)  # id of another plan item
    cognitive_mode = Column(String, default="execution")  # execution|exploration|consolidation
    reopen_after = Column(DateTime, nullable=True)
    revisit_count = Column(Integer, default=0)
    last_meaningful_progress_at = Column(DateTime, nullable=True)
    closure_reason = Column(String, nullable=True)
    parked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ACSPlanItem [{self.status}] {self.title[:40]} priority={self.priority}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan_date": self.plan_date.isoformat() if self.plan_date else None,
            "title": self.title,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "source_ref": self.source_ref,
            "estimated_turns": self.estimated_turns,
            "assigned_session_id": self.assigned_session_id,
            "result_summary": self.result_summary,
            "blocker_reason": self.blocker_reason,
            "depends_on": self.depends_on,
            "cognitive_mode": self.cognitive_mode,
            "reopen_after": self.reopen_after.isoformat() if self.reopen_after else None,
            "revisit_count": self.revisit_count,
            "last_meaningful_progress_at": self.last_meaningful_progress_at.isoformat() if self.last_meaningful_progress_at else None,
            "closure_reason": self.closure_reason,
            "parked_at": self.parked_at.isoformat() if self.parked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
