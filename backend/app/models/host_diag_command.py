"""
HostDiagCommand — the read-only diagnostic queue *and* the audit ledger.

A row with ``status='pending'`` is a command waiting for the agent to long-poll;
the same row records who asked, the exact argv, the verdict at each whitelist
layer, and the captured output. Nothing executes off-ledger. Read-only means undo
is never needed, but every diagnostic is accountable.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


# status values
PENDING = "pending"
RUNNING = "running"
DONE = "done"
DENIED_SERVER = "denied_server"
DENIED_AGENT = "denied_agent"
TIMEOUT = "timeout"
LOST = "lost"


class HostDiagCommand(Base):
    __tablename__ = "host_diag_command"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("managed_host.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    user_id = Column(String, nullable=True)

    requested_by = Column(String(24), nullable=False, default="chat")  # chat|deliberation|acs|api|web
    request_context = Column(String(255), nullable=True)               # message / run id

    argv = Column(JSONB, nullable=False)          # parsed argv array actually executed
    status = Column(String(20), nullable=False, default=PENDING, index=True)
    denied_reason = Column(Text, nullable=True)   # why a layer refused it

    exit_code = Column(Integer, nullable=True)
    stdout = Column(Text, nullable=True)
    stderr = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)   # dispatched to agent
    finished_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<HostDiagCommand(host_id={self.host_id}, argv={self.argv}, status={self.status})>"
