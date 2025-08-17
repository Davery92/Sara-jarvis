from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class Document(Base):
    __tablename__ = "document"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)  # S3/MinIO object key
    mime_type = Column(String)
    meta = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User")
    chunks = relationship("DocChunk", back_populates="document", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Document(title='{self.title}', mime_type='{self.mime_type}')>"


class DocChunk(Base):
    __tablename__ = "doc_chunk"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False)
    chunk_idx = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    breadcrumb = Column(String, default="")  # Title > H2 > H3
    embedding = Column(Vector(settings.embedding_dim), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    document = relationship("Document", back_populates="chunks")
    
    def __repr__(self):
        return f"<DocChunk(file_id='{self.file_id}', chunk_idx={self.chunk_idx})>"