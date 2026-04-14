"""ACS Interest Node — core of the Interest Graph."""

from sqlalchemy import Column, String, Text, DateTime, Float, Integer
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class ACSInterestNode(Base):
    __tablename__ = "acs_interest_node"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    label = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    fascination = Column(Float, default=0.5)
    depth = Column(Float, default=0.0)
    confidence = Column(Float, default=0.5)
    source = Column(String(50), default="self_discovery")
    source_detail = Column(Text, nullable=True)
    status = Column(String(30), default="active")
    times_engaged = Column(Integer, default=0)
    revisit_count = Column(Integer, default=0)
    last_engaged_at = Column(DateTime(timezone=True), nullable=True)
    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    embedding = Column(Vector(settings.embedding_dim), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ACSInterestNode {self.id[:8]} label={self.label!r}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "label": self.label,
            "description": self.description,
            "fascination": self.fascination,
            "depth": self.depth,
            "confidence": self.confidence,
            "source": self.source,
            "source_detail": self.source_detail,
            "status": self.status,
            "times_engaged": self.times_engaged,
            "revisit_count": self.revisit_count,
            "last_engaged_at": self.last_engaged_at.isoformat() if self.last_engaged_at else None,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
