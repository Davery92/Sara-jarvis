"""
Tangent Queue Model
Captures tangential questions/topics that arise during learning sessions.
Can be promoted to full learning topics or dismissed.
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class TangentQueue(Base):
    """Queued tangents from learning sessions"""
    __tablename__ = "tangent_queue"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    parent_topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="CASCADE"), nullable=False)

    # Tangent details
    tangent_description = Column(Text, nullable=False)
    source_context = Column(Text, nullable=True)  # What was being discussed when tangent arose
    priority = Column(Integer, default=3)  # 1-5
    status = Column(String(50), default="queued")  # queued, promoted_to_topic, dismissed
    promoted_topic_id = Column(String, ForeignKey("learning_topic.id", ondelete="SET NULL"), nullable=True)
    is_prerequisite = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    parent_topic = relationship("LearningTopic", foreign_keys=[parent_topic_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "parent_topic_id": self.parent_topic_id,
            "tangent_description": self.tangent_description,
            "source_context": self.source_context,
            "priority": self.priority,
            "status": self.status,
            "promoted_topic_id": self.promoted_topic_id,
            "is_prerequisite": self.is_prerequisite,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
