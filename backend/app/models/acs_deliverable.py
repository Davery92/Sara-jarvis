"""ACS deliverable tracking — UIs Sara built and shipped to an LXC for review."""

from sqlalchemy import Column, String, Text, DateTime, Integer
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ACSDeliverable(Base):
    __tablename__ = "acs_deliverable"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    vmid = Column(Integer, nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    kind = Column(String(30), nullable=False)
    ip = Column(String(45), nullable=True)
    port = Column(Integer, nullable=True)
    start_command = Column(Text, nullable=True)
    built_from = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pending_review", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    auto_destroy_at = Column(DateTime(timezone=True), nullable=True)
    destroyed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<ACSDeliverable {self.id[:8]} {self.title!r} status={self.status}>"

    def url(self) -> str | None:
        if not self.ip or not self.port:
            return None
        return f"http://{self.ip}:{self.port}"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "vmid": self.vmid,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "ip": self.ip,
            "port": self.port,
            "url": self.url(),
            "start_command": self.start_command,
            "built_from": self.built_from,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "auto_destroy_at": self.auto_destroy_at.isoformat() if self.auto_destroy_at else None,
            "destroyed_at": self.destroyed_at.isoformat() if self.destroyed_at else None,
        }
