from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class MemoryEdge(Base):
    __tablename__ = "memory_edge"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source_episode_id = Column(String, ForeignKey("episode.id", ondelete="CASCADE"), nullable=False)
    target_episode_id = Column(String, ForeignKey("episode.id", ondelete="CASCADE"), nullable=False)
    edge_type = Column(String, nullable=False)  # causal, temporal, semantic, etc.
    strength = Column(Float, nullable=False, default=1.0)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    source_episode = relationship("Episode", foreign_keys=[source_episode_id])
    target_episode = relationship("Episode", foreign_keys=[target_episode_id])
    
    def __repr__(self):
        return f"<MemoryEdge(source='{self.source_episode_id}', target='{self.target_episode_id}', type='{self.edge_type}')>"