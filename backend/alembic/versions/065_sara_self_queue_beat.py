"""Seed scheduled_job row for the interests → inbox promotion task.

Revision ID: 065_sara_self_queue_beat
Revises: 064_sara_user_tools
Create Date: 2026-05-09

When David's queue is empty AND a high-weight interest has gone stale,
this task promotes the interest into a queued sara_inbox item so Sara
pulls on it during her next think turn. This is the closing piece of the
interests loop — without it, interests are decoration she sees but has no
friction-free path to act on.

Cadence: every 20 min. The task is cheap (one COUNT, one SELECT, maybe
one INSERT) and has its own internal caps (daily limit, per-interest
cooldown, skip-if-busy), so polling at this rate is safe.
"""
from alembic import op
import sqlalchemy as sa


revision = "065_sara_self_queue_beat"
down_revision = "064_sara_user_tools"
branch_labels = None
depends_on = None


KEY = "sara-self-queue-promote"


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                :key,
                'Sara Self-Queue: Promote Stale Interest',
                'Auto-queues an inbox item from Sara''s top stale standing '
                'interest when she has nothing active to work on. Caps at '
                '6/day; respects 24h per-interest cooldown.',
                'autonomy',
                'app.tasks.sara_self_queue.promote_stale_interests_to_inbox',
                'interval', NULL, 1200, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                TRUE, TRUE, 'system', 'system'
            )
            ON CONFLICT (key) DO NOTHING
        """),
        {"key": KEY},
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM scheduled_job WHERE key = :key AND source = 'system'"),
        {"key": KEY},
    )
