"""ACS Self-Model — versioned self-understanding snapshots."""

from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSSelfModel(Base):
    __tablename__ = "acs_self_model"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    version = Column(Integer, default=1)
    content = Column(JSONB, nullable=False, default=dict)
    session_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ACSSelfModel {self.id[:8]} v{self.version}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "version": self.version,
            "content": self.content,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
