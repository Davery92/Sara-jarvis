"""ACS curiosity queue — topics Sara wants to explore autonomously."""

from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSCuriosity(Base):
    __tablename__ = "acs_curiosity_queue"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    topic = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="self")  # conversation|deliberation|consolidation|self
    priority = Column(Float, default=0.5)
    status = Column(String, nullable=False, default="queued")  # queued|exploring|explored|archived
    exploration_notes = Column(Text, nullable=True)
    related_note_ids = Column(JSONB, default=[])
    session_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ACSCuriosity {self.topic[:30]} status={self.status}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "topic": self.topic,
            "source": self.source,
            "priority": self.priority,
            "status": self.status,
            "exploration_notes": self.exploration_notes,
            "related_note_ids": self.related_note_ids,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
