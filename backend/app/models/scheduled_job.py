"""Scheduled job model — backs the DB-driven Celery beat scheduler."""
from sqlalchemy import Column, String, Boolean, Integer, Text, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class ScheduledJob(Base):
    """
    A periodic task entry that the custom DB-backed Celery beat scheduler
    reads on each tick. Editable from the settings API/UI without restarting beat.

    `schedule_kind` is either "cron" (use cron_expr, 5-field crontab string) or
    "interval" (use interval_seconds). Times in cron_expr are interpreted in
    the row's `timezone`.

    `source = 'system'` means the row was seeded from code and represents a
    canonical task; `source = 'user'` means it was created via the UI.
    """
    __tablename__ = "scheduled_job"
    __table_args__ = (
        CheckConstraint(
            "(schedule_kind = 'cron' AND cron_expr IS NOT NULL) OR "
            "(schedule_kind = 'interval' AND interval_seconds IS NOT NULL)",
            name="ck_scheduled_job_schedule_consistent",
        ),
        {"extend_existing": True},
    )

    key = Column(String(100), primary_key=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default="general")
    task_name = Column(String(255), nullable=False)

    schedule_kind = Column(String(20), nullable=False)  # "cron" | "interval"
    cron_expr = Column(String(255), nullable=True)
    interval_seconds = Column(Integer, nullable=True)
    timezone = Column(String(64), nullable=False, default="America/New_York")

    args = Column(JSONB, nullable=False, default=list)
    kwargs = Column(JSONB, nullable=False, default=dict)
    queue = Column(String(50), nullable=True)
    expires_seconds = Column(Integer, nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    editable = Column(Boolean, nullable=False, default=True)
    source = Column(String(20), nullable=False, default="system")
    # 'user' = surfaced by default in the settings UI (things David might want to retime).
    # 'system' = internal plumbing (watchers, pollers, heartbeats); hidden behind an "Advanced" toggle.
    visibility = Column(String(20), nullable=False, default="system")

    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)
    last_error = Column(Text, nullable=True)
    last_run_duration_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
