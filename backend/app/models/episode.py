from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class Episode(Base):
    __tablename__ = "episode"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=True, index=True)
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)    # user, assistant, system, tool
    content = Column(Text, nullable=False)
    importance = Column(Float, default=0.0)  # 0.0 to 1.0
    emotional_tone = Column(Text, nullable=True)
    topics = Column(Text, nullable=True)
    context_tags = Column(Text, nullable=True)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)
    memory_type = Column(String, nullable=True)  # conversation, note, etc.
    source = Column(String, nullable=True)  # chat, note, doc, system, tool
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)
    meta = Column(JSONB, default={})         # session_id, tool_name, note_id, doc_id, etc.
    emotion_metadata = Column(JSON, nullable=True)
    base_importance = Column(Float, nullable=True)
    importance_last_updated = Column(DateTime(timezone=True), nullable=True)
    user_rating = Column(Float, nullable=True)
    consolidated = Column(Boolean, nullable=True)
    embedding = Column(Vector(settings.embedding_dim), nullable=True)
    rating_boost = Column(Float, nullable=True)
    exploration_bonus = Column(Float, nullable=True)
    recall_relevance_ema = Column(Float, default=0.5)  # EMA of recall usefulness (0=always irrelevant, 1=always used)
    
    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<Episode(source='{self.source}', role='{self.role}', content='{self.content[:30]}...')>"