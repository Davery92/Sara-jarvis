"""Document model matching the main_simple.py table schema.

Note: models/doc.py has a different Document model with different columns
(storage_key, meta) that maps to the same 'document' table. This file
preserves the schema used by the main_simple.py routes which expect
filename, original_filename, file_path, content_text, is_processed columns.
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class DocumentLegacy(Base):
    """Document uploads with text extraction."""
    __tablename__ = "document"
    __table_args__ = {'extend_existing': True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    title = Column(String, default="")
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    content_text = Column(Text, default="")
    is_processed = Column(String, default="false")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())
