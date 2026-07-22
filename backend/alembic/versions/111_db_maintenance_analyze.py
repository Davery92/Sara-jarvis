"""Weekly DB maintenance — ANALYZE (audit finding B8).

Registers a Sunday 09:00 ET job that runs a full-database ANALYZE so the query
planner and any stats-reading self-diagnostics work off real row counts instead
of the fiction that nearly produced three false "dead feature" findings during
the 2026-07-22 audit.

Revision ID: 111_db_maintenance_analyze
Revises: 110_directives
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "111_db_maintenance_analyze"
down_revision = "110_directives"
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
                'db-maintenance-analyze',
                'DB Maintenance: ANALYZE',
                'Weekly full-database ANALYZE so the planner and stats-reading diagnostics work off real numbers (audit B8: only 35 of 287 tables had ever been analyzed).',
                'system',
                'app.tasks.db_maintenance.run_analyze',
                'cron', '0 9 * * 0', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'maintenance', 600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'db-maintenance-analyze'"))
