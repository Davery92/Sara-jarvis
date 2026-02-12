"""SharedContent model for the Content Inbox feature."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.db.base import Base
from app.core.config import settings


class SharedContent(Base):
    __tablename__ = "shared_content"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    content_type = Column(String(30), nullable=False)  # url, pdf, reddit, text, document
    original_url = Column(Text)
    title = Column(String(500))
    description = Column(Text)
    thumbnail_url = Column(Text)

    extracted_text = Column(Text)
    extraction_status = Column(String(20), nullable=False, default="pending")
    extraction_error = Column(Text)
    word_count = Column(Integer)

    storage_key = Column(String(500))
    original_filename = Column(String(500))
    mime_type = Column(String(100))
    file_size = Column(Integer)

    meta = Column(JSONB, default={})

    status = Column(String(20), nullable=False, default="unread")
    read_at = Column(DateTime(timezone=True))
    decided_at = Column(DateTime(timezone=True))

    discussed = Column(Boolean, default=False)
    consolidated = Column(Boolean, default=False)
    consolidated_at = Column(DateTime(timezone=True))
    episode_id = Column(String)

    embedding = Column(Vector(settings.embedding_dim), nullable=True)

    shared_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SharedContent id={self.id} type={self.content_type} title={self.title!r} status={self.status}>"
