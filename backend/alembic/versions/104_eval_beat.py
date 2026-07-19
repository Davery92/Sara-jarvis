"""Schedule the weekly tool-call reliability eval (Phase 5.6 / 9.4).

Revision ID: 104_eval_beat
Revises: 103_calendar_event_owner
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "104_eval_beat"
down_revision = "103_calendar_event_owner"
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
            'tool-call-eval', 'Weekly tool-call reliability eval',
            'Scripted tool-call suite vs the local model; pass-rate to the ledger.',
            'maintenance', 'app.tasks.interoception.tool_call_eval',
            'cron', '0 5 * * 1', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'maintenance', NULL, TRUE, TRUE, 'system'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    op.execute(text("DELETE FROM scheduled_job WHERE key = 'tool-call-eval'"))
