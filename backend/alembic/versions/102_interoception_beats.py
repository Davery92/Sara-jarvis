"""Schedule the interoception Celery beats (Phase 2).

- interoception-drain-events : every 2 min, redis buffer -> system_event
- interoception-self-check   : daily 08:05 ET body-scan
- interoception-purge-events : daily 04:20 ET, 30-day retention

Idempotent INSERT ... ON CONFLICT (key) DO NOTHING, matching migration 051.

Revision ID: 102_interoception_beats
Revises: 101_interoception_diagnostics
Create Date: 2026-07-19
"""
import json as _json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "102_interoception_beats"
down_revision = "101_interoception_diagnostics"
branch_labels = None
depends_on = None


JOBS = [
    # (key, display_name, description, category, task_name, kind, cron, interval, queue)
    ("interoception-drain-events", "Interoception: drain log buffer",
     "Move redis-buffered WARNING+ log records into system_event.",
     "maintenance", "app.tasks.interoception.drain_system_events",
     "interval", None, 120, "maintenance"),
    ("interoception-self-check", "Interoception: daily self-check",
     "Daily body-scan: failing tasks, queue depths, heartbeat, voice, backup.",
     "health", "app.tasks.interoception.self_check",
     "cron", "5 8 * * *", None, "health"),
    ("interoception-purge-events", "Interoception: purge old events",
     "30-day retention on the system_event ring buffer.",
     "maintenance", "app.tasks.interoception.purge_events",
     "cron", "20 4 * * *", None, "maintenance"),
]


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    if not _table_exists("scheduled_job"):
        return
    for (key, display_name, description, category, task_name,
         kind, cron_expr, interval_seconds, queue) in JOBS:
        op.execute(text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source
            ) VALUES (
                :key, :display_name, :description, :category, :task_name,
                :schedule_kind, :cron_expr, :interval_seconds, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, :queue, NULL,
                TRUE, TRUE, 'system'
            )
            ON CONFLICT (key) DO NOTHING
        """).bindparams(
            key=key, display_name=display_name, description=description,
            category=category, task_name=task_name, schedule_kind=kind,
            cron_expr=cron_expr, interval_seconds=interval_seconds, queue=queue,
        ))


def downgrade():
    for job in JOBS:
        op.execute(text("DELETE FROM scheduled_job WHERE key = :k").bindparams(k=job[0]))
