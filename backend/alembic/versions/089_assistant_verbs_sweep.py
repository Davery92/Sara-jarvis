"""Assistant verbs sweep — SARA_UNLEASHED Phase C.1.

Registers the deterministic verbs sweep: unhandled-important-email drafts
(capped 3/day, oldest first) + commitment nudges, every 30 min during
waking hours. Deliberation stays free to handle judgment calls; this makes
"does the obviously-useful thing happen" deterministic instead of waiting on
an LLM to volunteer it (R5/R6 — 0 email_draft rows ever, despite the handler
being fully built and send-proof).

Revision ID: 089_assistant_verbs_sweep
Revises: 088_notification_blocked_count
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "089_assistant_verbs_sweep"
down_revision = "088_notification_blocked_count"
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
                'assistant-verbs-sweep',
                'Assistant Verbs Sweep',
                'Deterministic email drafts (unhandled important email >4h old, capped 3/day) + commitment nudges, every 30 min during waking hours.',
                'cognitive',
                'app.tasks.assistant_verbs.assistant_verbs_sweep',
                'cron', '*/30 8-20 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300,
                TRUE, TRUE, 'system', 'system'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'assistant-verbs-sweep'"))
