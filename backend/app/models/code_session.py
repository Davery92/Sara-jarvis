"""
Code Session model — persistent state for chat "code mode".

A CodeSession binds a chat conversation to a coding agent that runs on the
sara VM (10.185.1.176). While a session is active, every message in the
conversation is routed to the coding harness instead of to Sara-the-assistant.

The disk checkout (a git worktree on the VM) IS the persistent context; the
`transcript` / `session_log` columns are the compacted reasoning layer the
harness rebuilds each turn on top of a fresh, ground-truth `git status` header.

See CODE_MODE_DESIGN.md.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class CodeSession(Base):
    __tablename__ = "code_session"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String, nullable=True, index=True)

    # Project / repo binding
    dev_project_id = Column(String, nullable=True)
    repo_owner = Column(String(255), nullable=True)
    repo_name = Column(String(255), nullable=True)
    branch = Column(String(255), nullable=True)
    workdir = Column(String(1000), nullable=True)  # worktree path on the VM

    # Runtime state machine: idle | running | stopping
    state = Column(String(20), nullable=False, default="idle")
    active = Column(Boolean, nullable=False, default=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)

    # Reasoning layers (disk is the source of truth; these are the compacted overlay)
    transcript = Column(JSONB, nullable=False, default=list)   # recent turns, verbatim
    session_log = Column(Text, nullable=True)                  # summarized older turns
    queue = Column(JSONB, nullable=False, default=list)        # messages queued while RUNNING

    turns = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<CodeSession(id={self.id}, repo={self.repo_owner}/{self.repo_name}, "
            f"branch={self.branch}, state={self.state}, active={self.active})>"
        )

    @property
    def repo_slug(self) -> str | None:
        if self.repo_owner and self.repo_name:
            return f"{self.repo_owner}/{self.repo_name}"
        return None
