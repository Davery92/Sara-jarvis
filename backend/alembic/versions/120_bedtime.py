"""Bedtime intelligence (§6.3.4) — evening winddown nudge.

Runs hourly 20:00-22:00 ET; nudges only when near the learned winddown window
AND there's a reason (sleep debt / early start). Passive, drops after two ignores.

Revision ID: 120_bedtime
Revises: 119_why_trace
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "120_bedtime"
down_revision = "119_why_trace"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
        ) VALUES (
            'bedtime-intelligence',
            'Bedtime nudge',
            'Evening winddown nudge timed from the learned winddown window + sleep debt + tomorrow''s first event (§6.3.4). Passive, anti-nag capped.',
            'wellness',
            'app.tasks.bedtime.maybe_nudge',
            'cron', '0 20-22 * * *', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'cognitive', 300, TRUE, TRUE, 'system', 'user'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM scheduled_job WHERE key = 'bedtime-intelligence'"))
