"""ACS directive — messages from David to Sara's autonomous cognition system."""

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSDirective(Base):
    __tablename__ = "acs_directive"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    directive_type = Column(String, nullable=False)  # focus|stop|context|redirect|question
    content = Column(Text, nullable=False)
    priority = Column(String, default="normal")  # urgent|normal|low
    status = Column(String, default="pending")  # pending|acknowledged|acted_on|expired
    source = Column(String, default="api")  # david_chat|frontend|api
    response = Column(Text, nullable=True)  # Sara's acknowledgement/response
    created_at = Column(DateTime, server_default=func.now())
    acknowledged_at = Column(DateTime, nullable=True)
    expired_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<ACSDirective [{self.directive_type}] {self.content[:40]} status={self.status}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "directive_type": self.directive_type,
            "content": self.content,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "response": self.response,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
        }
