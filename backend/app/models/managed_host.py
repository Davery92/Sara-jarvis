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

    # --- Fleet agent transport (see FLEET_DESIGN.md §6.1) --------------------
    # A ManagedHost may be reached over SSH ("ssh"), the push agent ("agent"),
    # or both. All columns are nullable so pre-existing SSH-only rows are valid.
    transport = Column(String(16), nullable=False, default="ssh")   # ssh | agent | both
    machine_id = Column(String(64), nullable=True, index=True)      # /etc/machine-id — joins agent → row
    agent_token_hash = Column(String(64), nullable=True)            # sha256 of the per-host bearer token
    agent_version = Column(String(16), nullable=True)
    agent_enrolled_at = Column(DateTime(timezone=True), nullable=True)
    agent_last_report_at = Column(DateTime(timezone=True), nullable=True)  # freshness / offline detection
    agent_snapshot = Column(JSONB, nullable=True)                   # latest full telemetry payload
    agent_alert_state = Column(JSONB, nullable=True)                # per-rule edge state (see alerts.py)

    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<ManagedHost(name={self.name}, "
            f"{self.username}@{self.hostname}:{self.port}, status={self.last_status})>"
        )
