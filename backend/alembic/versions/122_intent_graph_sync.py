"""Periodic intent-graph sync (SINGULAR_SARA_MASTER_PLAN §C3).

Registers a 15-minute job keeping the durable `intent` table current with
the live projection, instead of relying on someone remembering to call
POST /api/diagnostics/intent-graph/sync by hand.

Revision ID: 122_intent_graph_sync
Revises: 121_singular_sara_tables
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa


revision = "122_intent_graph_sync"
down_revision = "121_singular_sara_tables"
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
                enabled, editable, source, visibility, singular_class
            ) VALUES (
                'intent-graph-sync',
                'Intent Graph Sync',
                'Keeps the durable intent table current with reminders, standing orders, missions, threads, tasks, and interests (SINGULAR_SARA_MASTER_PLAN §C3) — read-only over sources, upsert-only into intent.',
                'system',
                'app.tasks.intent_graph.sync_intent_graph',
                'interval', NULL, 900, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'maintenance', 300,
                TRUE, TRUE, 'system', 'system', 'maintenance'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'intent-graph-sync'"))
