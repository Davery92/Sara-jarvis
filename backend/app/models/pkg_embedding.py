"""PostgreSQL shadow table for PKG node embeddings (vector search via pgvector)."""
from sqlalchemy import Column, String, Text, DateTime, Float
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings


class PkgEmbedding(Base):
    __tablename__ = "pkg_embedding"
    __table_args__ = {"extend_existing": True}

    pkg_id = Column(String, primary_key=True)
    node_type = Column(String, nullable=False, index=True)  # Person, Preference, etc.
    content_text = Column(Text, nullable=False)  # Text representation used for embedding
    embedding = Column(Vector(settings.embedding_dim), nullable=True)
    confidence = Column(Float, default=0.7)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
