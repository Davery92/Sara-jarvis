"""
ManagedHost model — registry of Linux machines Sara can reach over SSH.

This is what lets David say "Sara, check out <server>" and have her connect,
inspect specs (CPU / memory / disk / OS / Docker / GPU), and report back. It is
also the target registry for dispatching autonomous agents to arbitrary hosts
(not just the sara sandbox VM).

Auth is SSH-key based: David adds Sara's public key (default identity
``~/.ssh/sara_agent``, same key the VM bridge uses) to ``authorized_keys`` on
each machine, then registers it here. No passwords are stored.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ManagedHost(Base):
    __tablename__ = "managed_host"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)

    # Friendly handle used in chat ("check out gpu-box"). Lowercased, unique per user.
    name = Column(String(64), nullable=False, index=True)
    hostname = Column(String(255), nullable=False)   # IP or DNS name
    username = Column(String(64), nullable=False, default="sara")
    port = Column(Integer, nullable=False, default=22)
    ssh_key_path = Column(String(500), nullable=False, default="~/.ssh/sara_agent")

    description = Column(Text, nullable=True)         # free-form note ("home GPU rig")
    tags = Column(JSONB, nullable=False, default=list)

    # Cached results of the last inspection (structured spec) + when it ran.
    last_inspection = Column(JSONB, nullable=True)
    last_status = Column(String(32), nullable=True)  # connected | unreachable | auth_failed | error
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<ManagedHost(name={self.name}, "
            f"{self.username}@{self.hostname}:{self.port}, status={self.last_status})>"
        )
