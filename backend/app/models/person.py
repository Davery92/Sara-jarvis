"""
Person model — the people layer (PHENOMENAL_ASSISTANT_PLAN.md Phase 2).

Postgres is source of truth for interaction state (who, how often, when
last); PKG_Person stays the semantic/fact layer, linked via pkg_person_ref.
Fed by email_sync (sender upserts) and pkg_extractor (chat-mention bumps).
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class Person(Base):
    __tablename__ = "person"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)

    canonical_name = Column(String(255), nullable=False)
    emails = Column(JSONB, nullable=False, default=list)
    aliases = Column(JSONB, nullable=False, default=list)
    pkg_person_ref = Column(String, nullable=True)

    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)
    last_interaction_kind = Column(String(32), nullable=True)  # email_in|email_out|meeting|mention

    interaction_count = Column(Integer, nullable=False, default=0)
    mention_count = Column(Integer, nullable=False, default=0)
    importance = Column(Float, nullable=False, default=0.5)
    is_vip = Column(Boolean, nullable=False, default=False)
    muted = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Person(name={self.canonical_name}, interactions={self.interaction_count})>"
