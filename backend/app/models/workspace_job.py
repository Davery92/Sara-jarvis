"""
WorkspaceJob Model (SURFACES_DESIGN.md §B2)

A declared, bounded pipeline over existing capabilities — e.g. "every email
from Laura in the last 3 days with attachments → pull the attachments into a
folder". Runs as a Celery task, live-patches a progress surface that becomes a
file_list on completion, and emits exactly one completion notification.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class WorkspaceJob(Base):
    __tablename__ = "workspace_job"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("app_user.id"), nullable=False, index=True)

    job_type = Column(String(50), nullable=False)  # email_attachments_fetch | files_collect
    params = Column(JSONB, nullable=False, default=dict)

    # pending | running | completed | failed
    status = Column(String(20), nullable=False, default="pending", index=True)

    # The progress/file_list surface this job drives.
    surface_id = Column(String(36), nullable=True)

    # {"files": [{"name","bucket","key","size","mime"}], "summary": "..."}
    result = Column(JSONB, nullable=False, default=dict)
    error = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "job_type": self.job_type,
            "params": self.params,
            "status": self.status,
            "surface_id": self.surface_id,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
