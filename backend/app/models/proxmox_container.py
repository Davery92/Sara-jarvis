"""Proxmox container tracking for ACS dynamic provisioning."""

from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class ProxmoxContainer(Base):
    __tablename__ = "proxmox_container"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vmid = Column(Integer, unique=True, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)
    hostname = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=True)
    preset = Column(String(30), nullable=False)
    cores = Column(Integer, nullable=False)
    memory_mb = Column(Integer, nullable=False)
    disk_gb = Column(Integer, nullable=False)
    persistent = Column(Boolean, default=False)
    purpose = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="creating")
    created_at = Column(DateTime, server_default=func.now())
    destroyed_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<ProxmoxContainer vmid={self.vmid} status={self.status}>"

    def to_dict(self):
        return {
            "id": self.id,
            "vmid": self.vmid,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "preset": self.preset,
            "cores": self.cores,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
            "persistent": self.persistent,
            "purpose": self.purpose,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "destroyed_at": self.destroyed_at.isoformat() if self.destroyed_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }
