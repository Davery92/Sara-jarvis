"""System Wiring Check — weekly self-audit (Phase 5.2, SARA_100_PLAN).

Registers the Sunday 8 AM ET standing verification loop: unscheduled-task
coverage, scheduled_job health, learning-table freshness, deployed-code
staleness. Green folds into the weekly digest; red raises a Needs-You
inbox item naming the broken loop.

Revision ID: 086_system_wiring_check
Revises: 085_drop_detected_pattern
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "086_system_wiring_check"
down_revision = "085_drop_detected_pattern"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'system-wiring-check',
                'System Wiring Check',
                'Weekly self-audit: unscheduled Celery tasks, unhealthy scheduled_job rows, stale learning tables, deployed-code drift. Green folds into the weekly digest; red raises a Needs-You inbox item.',
                'system',
                'app.tasks.system_wiring_check.run_check',
                'cron', '0 8 * * 0', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'low_priority', 600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'system-wiring-check'"))
