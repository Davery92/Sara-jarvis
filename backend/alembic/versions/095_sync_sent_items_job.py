"""Sent-items sync scheduled job — SARA_UNLEASHED Phase D.2.

Revision ID: 095_sync_sent_items_job
Revises: 094_notify_legacy_limit_tunables
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "095_sync_sent_items_job"
down_revision = "094_notify_legacy_limit_tunables"
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
                'sync-sent-items',
                'Sync Sent Items',
                'Syncs the Sent folder so the person layer sees who David wrote to, not just who wrote to him — unlocks reply-latency signals.',
                'people',
                'app.tasks.email_sync.sync_sent_items',
                'interval', NULL, 900, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'low_priority', 300,
                TRUE, TRUE, 'system', 'system'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'sync-sent-items'"))
