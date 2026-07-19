"""Weekly self-audit ritual beat — Sunday 18:30 ET (Phase 9.6).

Revision ID: 107_self_audit_beat
Revises: 106_interest_strikes
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "107_self_audit_beat"
down_revision = "106_interest_strikes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "scheduled_job" not in sa.inspect(bind).get_table_names():
        return
    op.execute(text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds, enabled, editable, source
        ) VALUES (
            'weekly-self-audit', 'Weekly self-audit (state of me)',
            'Sara reviews her ledger, drift, feed quality + muted interests -> Sunday journal.',
            'maintenance', 'app.tasks.interoception.weekly_self_audit',
            'cron', '30 18 * * 0', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'maintenance', NULL, TRUE, TRUE, 'system'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    op.execute(text("DELETE FROM scheduled_job WHERE key = 'weekly-self-audit'"))
