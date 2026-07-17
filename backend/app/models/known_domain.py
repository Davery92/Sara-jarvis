"""
Known Domain Model
Tracks domains David is already proficient in, used for generating analogies
during learning sessions.
"""
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class KnownDomain(Base):
    """Domains David already knows — used for analogy generation"""
    __tablename__ = "known_domain"
    __table_args__ = (
        UniqueConstraint('user_id', 'domain_name', name='uq_known_domain_user_name'),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # Domain details
    domain_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    proficiency = Column(String(50), default="intermediate")  # beginner, intermediate, expert
    key_concepts = Column(JSONB, default=list)  # List of key concepts David knows in this domain

    # Timestamps
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "domain_name": self.domain_name,
            "description": self.description,
            "proficiency": self.proficiency,
            "key_concepts": self.key_concepts or [],
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
