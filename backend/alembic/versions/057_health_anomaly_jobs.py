"""Seed scheduled_job rows for nightly health-baseline recompute and hourly anomaly detection.

Revision ID: 057_health_anomaly_jobs
Revises: 056_external_workout
Create Date: 2026-05-05

The DB-backed Celery beat scheduler reads its schedule from scheduled_job. These
two rows wire up the Phase-3 health analytics:

- recompute_health_baselines runs nightly at 2:15 AM ET (after midnight,
  before morning brief at 7 AM).
- detect_health_anomalies runs every 30 minutes during waking hours (6 AM–11 PM ET)
  to surface anomalies promptly without spamming overnight.
"""
from alembic import op
import sqlalchemy as sa


revision = "057_health_anomaly_jobs"
down_revision = "056_external_workout"
branch_labels = None
depends_on = None


SEED = [
    {
        "key": "health-baseline-recompute",
        "display_name": "Health Baseline Recompute",
        "description": (
            "Recomputes 7-day and 30-day rolling baselines (avg, std, min, max) "
            "for every tracked health metric. Runs nightly at 2:15 AM ET so the "
            "baselines are fresh before the morning brief."
        ),
        "category": "health",
        "task_name": "app.tasks.health_baselines.recompute_health_baselines",
        "schedule_kind": "cron",
        "cron_expr": "15 2 * * *",
        "interval_seconds": None,
        "queue": "health",
    },
    {
        "key": "health-anomaly-detect",
        "display_name": "Health Anomaly Detection",
        "description": (
            "Compares latest readings against 7-day baselines (z-score) and "
            "writes alerts/insights for material deviations. Runs every 30 min "
            "during waking hours; pushes to phone for warning/urgent severities."
        ),
        "category": "health",
        "task_name": "app.tasks.health_baselines.detect_health_anomalies",
        "schedule_kind": "cron",
        "cron_expr": "*/30 6-23 * * *",
        "interval_seconds": None,
        "queue": "health",
    },
]


def upgrade():
    bind = op.get_bind()
    for row in SEED:
        bind.execute(
            sa.text("""
                INSERT INTO scheduled_job (
                    key, display_name, description, category, task_name,
                    schedule_kind, cron_expr, interval_seconds, timezone,
                    args, kwargs, queue, expires_seconds,
                    enabled, editable, source, visibility
                ) VALUES (
                    :key, :display_name, :description, :category, :task_name,
                    :schedule_kind, :cron_expr, :interval_seconds, 'America/New_York',
                    '[]'::jsonb, '{}'::jsonb, :queue, NULL,
                    TRUE, TRUE, 'system', 'system'
                )
                ON CONFLICT (key) DO NOTHING
            """),
            row,
        )


def downgrade():
    bind = op.get_bind()
    for row in SEED:
        bind.execute(
            sa.text("DELETE FROM scheduled_job WHERE key = :key AND source = 'system'"),
            {"key": row["key"]},
        )
