from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class Note(Base):
    __tablename__ = "note"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    folder_id = Column(UUID(as_uuid=True), ForeignKey("folder.id", ondelete="CASCADE"), nullable=True)
    title = Column(String, default="")
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.embedding_dim))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    folder = relationship("Folder", back_populates="notes")
    
    def __repr__(self):
        return f"<Note(title='{self.title[:30]}...')>"