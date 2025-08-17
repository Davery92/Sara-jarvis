from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class Episode(Base):
    __tablename__ = "episode"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    source = Column(String, nullable=False)  # chat, note, doc, system, tool
    role = Column(String, nullable=False)    # user, assistant, system, tool
    content = Column(Text, nullable=False)
    meta = Column(JSONB, default={})         # session_id, tool_name, note_id, doc_id, etc.
    importance = Column(Float, default=0.0)  # 0.0 to 1.0
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    memory_vectors = relationship("MemoryVector", back_populates="episode", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Episode(source='{self.source}', role='{self.role}', content='{self.content[:30]}...')>"


class MemoryVector(Base):
    __tablename__ = "memory_vector"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episode.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(settings.embedding_dim), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    episode = relationship("Episode", back_populates="memory_vectors")
    
    def __repr__(self):
        return f"<MemoryVector(episode_id='{self.episode_id}', chunk_index={self.chunk_index})>"


class MemoryHot(Base):
    __tablename__ = "memory_hot"

    episode_id = Column(UUID(as_uuid=True), ForeignKey("episode.id", ondelete="CASCADE"), primary_key=True)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now())
    accesses = Column(Integer, default=1)
    
    # Relationships
    episode = relationship("Episode")
    
    def __repr__(self):
        return f"<MemoryHot(episode_id='{self.episode_id}', accesses={self.accesses})>"