"""ACS show-David buffer — discoveries and insights Sara wants to share."""

from sqlalchemy import Column, String, Text, DateTime, Float, Boolean
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSShowDavid(Base):
    __tablename__ = "acs_show_david_buffer"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False, default="discovery")  # discovery|insight|question|recommendation
    priority = Column(Float, default=0.5)
    shown = Column(Boolean, default=False)
    shown_at = Column(DateTime, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    related_note_id = Column(String, nullable=True)
    dedupe_key = Column(String, nullable=True, index=True)
    delivery_status = Column(String, nullable=False, default="queued")  # queued|suppressed|merged|delivered
    suppression_reason = Column(Text, nullable=True)
    merged_into_id = Column(String, nullable=True)
    shared_reason = Column(String, nullable=False, default="interesting_discovery")
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<ACSShowDavid {self.title[:30]} shown={self.shown}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "content": self.content,
            "category": self.category,
            "priority": self.priority,
            "shown": self.shown,
            "shown_at": self.shown_at.isoformat() if self.shown_at else None,
            "session_id": self.session_id,
            "related_note_id": self.related_note_id,
            "dedupe_key": self.dedupe_key,
            "delivery_status": self.delivery_status,
            "suppression_reason": self.suppression_reason,
            "merged_into_id": self.merged_into_id,
            "shared_reason": self.shared_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
