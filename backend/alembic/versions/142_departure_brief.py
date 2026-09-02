"""Departure brief — MORNING_NOTIFICATIONS_PLAN_2026_08_18 Phase 4.

Registers the every-5-min beat window (6-10 AM ET) that fires the second
(and last) morning push, timed ~25 min before David's usual departure.

Revision ID: 142_departure_brief
Revises: 141_notify_suppress_reason
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa


revision = "142_departure_brief"
down_revision = "141_notify_suppress_reason"
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
                'departure-brief',
                'Departure Brief',
                'Every 5 min, 6-10 AM weekdays: fires the second morning push ~25 min before David leaves — first calendar event, commute weather, gym-bag reminder, and anything queued for departure timing.',
                'system',
                'app.tasks.departure_brief.send_departure_brief',
                'cron', '*/5 6-10 * * 1-5', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'departure-brief'"))
