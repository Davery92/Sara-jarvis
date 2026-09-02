"""Schedule recovery of world attention cognition wakes.

Revision ID: 146_world_attention_cognition
Revises: 145_world_interpreter_recovery
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "146_world_attention_cognition"
down_revision = "145_world_interpreter_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds,
            enabled, editable, source, visibility
        ) VALUES (
            'world-state-attention-drain', 'World Attention Drain',
            'Recovers durable attention wakes and routes them through Sara''s single ambient kernel.',
            'system', 'app.tasks.world_state.drain_attention',
            'interval', NULL, 60, 'UTC', '[]'::jsonb, '{"limit": 20}'::jsonb,
            'critical', 55, TRUE, TRUE, 'system', 'debug'
        ) ON CONFLICT (key) DO UPDATE SET
            task_name = EXCLUDED.task_name,
            interval_seconds = EXCLUDED.interval_seconds,
            kwargs = EXCLUDED.kwargs,
            enabled = TRUE
    """))


def downgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM scheduled_job WHERE key='world-state-attention-drain'"
    ))
