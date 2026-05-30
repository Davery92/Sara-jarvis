"""Narrator: seed scheduled_job for the trigger sweep.

Revision ID: 067_narrator_beat
Revises: 066_system_events
Create Date: 2026-05-17

Adds the periodic beat that runs every registered narrator trigger once.
30 minutes is the v1 cadence — most triggers have their own per-instance
cooldowns (24h for stale_pr), so the sweep is cheap when nothing has
changed. Editable from the settings UI.
"""
from alembic import op
import sqlalchemy as sa


revision = "067_narrator_beat"
down_revision = "066_system_events"
branch_labels = None
depends_on = None


KEY = "narrator-sweep-triggers"


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
                :key,
                'Narrator: Sweep Triggers',
                'Runs every registered narrator trigger once. Per-trigger '
                'cooldowns gate actual emission (default 24h), so most '
                'sweeps are no-ops.',
                'narrator',
                'app.tasks.narrator.sweep_triggers',
                'interval', NULL, 1800, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {"key": KEY},
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM scheduled_job WHERE key = :key"),
        {"key": KEY},
    )
