"""Schedule recovery of pending world-event interpretations.

Revision ID: 145_world_interpreter_recovery
Revises: 144_live_activity_delivery
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "145_world_interpreter_recovery"
down_revision = "144_live_activity_delivery"
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
            'world-state-interpretation-drain', 'World Interpretation Drain',
            'Recovers rich local-model interpretation work after dispatch or model outages.',
            'system', 'app.tasks.world_state.drain_interpretations',
            'interval', NULL, 30, 'UTC', '[]'::jsonb, '{"limit": 20}'::jsonb,
            'critical', 25, TRUE, TRUE, 'system', 'debug'
        ) ON CONFLICT (key) DO UPDATE SET
            task_name = EXCLUDED.task_name,
            interval_seconds = EXCLUDED.interval_seconds,
            kwargs = EXCLUDED.kwargs,
            enabled = TRUE
    """))


def downgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM scheduled_job WHERE key='world-state-interpretation-drain'"
    ))
