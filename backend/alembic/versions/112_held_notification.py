"""Held notifications — the unified delivery policy's overnight queue (§3.6).

When David is asleep (sensed via iPhone Focus + home quiet + learned rhythm),
non-critical pushes are HELD here instead of buzzing his phone at 5 AM (fixes
audit finding N1). A flush task delivers them as a single digest at sensed wake.

Persistent (not the in-memory NotificationQueue) so a hold survives a restart
across the night. Also registers the every-15-min flush job.

Revision ID: 112_held_notification
Revises: 111_db_maintenance_analyze
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "112_held_notification"
down_revision = "111_db_maintenance_analyze"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "held_notification",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String, nullable=False, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("category", sa.String, nullable=True),
        sa.Column("priority", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True),
        sa.Column("topic", sa.String, nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("why_trace", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("held_reason", sa.String, nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="held"),  # held | delivered | dropped
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_held_notification_pending",
        "held_notification",
        ["user_id", "status"],
    )

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
                'delivery-policy-flush',
                'Delivery Policy: flush held',
                'Every 15 min: if David is awake, deliver notifications held overnight as one digest (unified delivery policy §3.6 / N1 fix).',
                'system',
                'app.tasks.delivery_flush.flush_held_notifications',
                'interval', NULL, 900, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'delivery-policy-flush'"))
    op.drop_index("ix_held_notification_pending", table_name="held_notification")
    op.drop_table("held_notification")
