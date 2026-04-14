"""ACS Interest Edge — relationships between interest nodes."""

from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSInterestEdge(Base):
    __tablename__ = "acs_interest_edge"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    source_node_id = Column(String, nullable=False, index=True)
    target_node_id = Column(String, nullable=False, index=True)
    relationship = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    strength = Column(Float, default=0.5)
    discovered_during_mode = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ACSInterestEdge {self.id[:8]} {self.relationship}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "relationship": self.relationship,
            "description": self.description,
            "strength": self.strength,
            "discovered_during_mode": self.discovered_during_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
