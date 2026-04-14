"""Durable ACS transcript storage."""

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSSessionTranscript(Base):
    __tablename__ = "acs_session_transcript"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True, unique=True)
    mode = Column(String(20), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    transcript_json = Column(JSONB, nullable=False, default=dict)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ACSSessionTranscript {self.session_id[:8]}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "mode": self.mode,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "transcript_json": self.transcript_json,
            "raw_text": self.raw_text,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
