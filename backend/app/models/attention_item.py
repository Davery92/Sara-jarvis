"""SQLAlchemy model for autonomy_attention_item table."""

from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class AttentionItem(Base):
    __tablename__ = "autonomy_attention_item"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(String(255), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text)
    category = Column(String(50), nullable=False, default="general")
    priority = Column(String(20), nullable=False, default="normal")
    source = Column(String(50), nullable=False, default="unified_agent")
    status = Column(String(20), nullable=False, default="new")
    dedupe_key = Column(String(255))
    payload = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True))
    archived_at = Column(DateTime(timezone=True))
