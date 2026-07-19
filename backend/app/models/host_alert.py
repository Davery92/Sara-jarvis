"""
HostAlert — the edge-trigger ledger for fleet health rules.

An alert fires on the false→true edge of a rule (disk crosses 95%, host goes
offline) and resolves when the condition clears. One *open* row per (host, rule);
resolved rows stay for history. The alert engine (services/fleet/alerts.py) emits
an event onto the event bus on the firing edge — it never pushes to David directly
(the deliberation gate + attention economy decide that).
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class HostAlert(Base):
    __tablename__ = "host_alert"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("managed_host.id", ondelete="CASCADE"),
                     nullable=False, index=True)

    rule = Column(String(48), nullable=False, index=True)   # disk_critical | host_offline | ...
    severity = Column(String(16), nullable=False, default="normal")  # high | normal | low
    state = Column(String(16), nullable=False, default="firing")     # firing | resolved
    detail = Column(JSONB, nullable=True)                   # numbers at fire time (pct, mount, ...)

    fired_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    notified = Column(Boolean, nullable=False, default=False)  # did we emit an intent for this edge

    def __repr__(self):
        return f"<HostAlert(host_id={self.host_id}, rule={self.rule}, state={self.state})>"
