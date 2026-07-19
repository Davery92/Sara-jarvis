"""
Surface Model — ephemeral interactive UI (SURFACES_DESIGN.md Part B)

A surface is a server-driven interactive app Sara composes from a closed
component vocabulary: a JSON spec (what to render) plus mutable state (what the
user has done — checked items, form values). Distinct from an Artifact, which
is persistent, mostly-static content bound to a conversation; surfaces carry
interaction state, expiry, and device routing.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class Surface(Base):
    __tablename__ = "surface"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("app_user.id"), nullable=False, index=True)
    conversation_id = Column(String(36), nullable=True)

    title = Column(String(255), nullable=False)
    surface_type = Column(String(50), nullable=False, default="custom")

    # The render spec (closed component vocabulary) and mutable interaction
    # state, kept separate so a spec update never clobbers what the user did.
    spec = Column(JSONB, nullable=False)
    state = Column(JSONB, nullable=False, default=dict)

    # active | torn_down | expired
    status = Column(String(20), nullable=False, default="active", index=True)
    version = Column(Integer, nullable=False, default=1)

    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "surface_type": self.surface_type,
            "spec": self.spec,
            "state": self.state,
            "status": self.status,
            "version": self.version,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
