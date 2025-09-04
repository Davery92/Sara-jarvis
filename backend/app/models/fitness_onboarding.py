from sqlalchemy import Column, String, DateTime, JSON, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func
import uuid
from app.db.base import Base

class FitnessOnboardingSession(Base):
    __tablename__ = "fitness_onboarding_sessions"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    stage = Column(String(100), nullable=False, default="profile")  # profile, history, context, goals, preferences, preview, confirm
    collected_answers = Column(JSON, nullable=False, default=dict)  # normalized answers
    raw_answers = Column(JSON, nullable=False, default=dict)  # original user inputs
    proposed_plan_draft_id = Column(String(255), nullable=True)  # UUID from plan generator
    status = Column(String(50), nullable=False, default="active")  # active, completed, abandoned
    current_question = Column(Text, nullable=True)  # last question asked
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def to_dict(self):
        return {
            "session_id": str(self.id),
            "user_id": str(self.user_id),
            "stage": self.stage,
            "collected_answers": self.collected_answers,
            "status": self.status,
            "current_question": self.current_question,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
