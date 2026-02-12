"""Document chunk model (main_simple.py table schema)."""
from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DocumentChunk(Base):
    """Document chunks with embeddings for RAG."""
    __tablename__ = "document_chunk"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    embedding = Column(Text, nullable=True)  # Vector handled at runtime
    created_at = Column(DateTime, server_default=func.now())
