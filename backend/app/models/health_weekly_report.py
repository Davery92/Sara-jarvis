"""Weekly health consolidation report (Sunday 6 AM ET pipeline)."""
from sqlalchemy import Column, String, Date, Text, DateTime, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class HealthWeeklyReport(Base):
    __tablename__ = "health_weekly_report"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_hwr_user_week"),
        Index("ix_hwr_week_end", "week_end"),
        {"extend_existing": True},
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)

    stats_json = Column(JSONB, nullable=False)
    recovery_json = Column(JSONB)
    activity_json = Column(JSONB)

    headline = Column(String(255))
    full_markdown = Column(Text)

    model_used = Column(String(100))
    status = Column(String(20), nullable=False, default="pending")  # pending | running | complete | failed
    error = Column(Text)

    push_sent_at = Column(DateTime(timezone=True))
    note_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
