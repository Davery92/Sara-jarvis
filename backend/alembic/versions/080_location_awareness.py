"""Location awareness: known places, location-triggered reminders, location event log.

Revision ID: 080_location_awareness
Revises: 079_attention_policy_snapshot
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa


revision = "080_location_awareness"
down_revision = "079_attention_policy_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "known_place" not in existing_tables:
        op.create_table(
            "known_place",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("place_type", sa.String(50), nullable=False, server_default="other"),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("radius_m", sa.Integer(), nullable=False, server_default="150"),
            sa.Column("source", sa.String(20), nullable=False, server_default="user"),
            sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_known_place_user_id", "known_place", ["user_id"])

    if "location_trigger" not in existing_tables:
        op.create_table(
            "location_trigger",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trigger_on", sa.String(10), nullable=False),  # 'enter' | 'exit'
            sa.Column("place_id", sa.String(), sa.ForeignKey("known_place.id", ondelete="CASCADE"), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("radius_m", sa.Integer(), nullable=True),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("reminder_title", sa.String(), nullable=False),
            sa.Column("reminder_description", sa.Text(), nullable=True),
            sa.Column("recurring", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("status", sa.String(20), nullable=False, server_default="armed"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_location_trigger_user_id", "location_trigger", ["user_id"])
        op.create_index("ix_location_trigger_status", "location_trigger", ["status"])

    if "location_event" not in existing_tables:
        op.create_table(
            "location_event",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("accuracy", sa.Float(), nullable=True),
            sa.Column("place_id", sa.String(), sa.ForeignKey("known_place.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_type", sa.String(10), nullable=False),  # 'report' | 'enter' | 'exit'
            sa.Column("source", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_location_event_user_created", "location_event", ["user_id", "created_at"])

    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'location-trigger-expiry',
                'Location Trigger Expiry',
                'Hourly sweep that expires armed one-shot location triggers past their expires_at.',
                'notifications',
                'app.tasks.location.location_trigger_expiry',
                'cron', '15 * * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300,
                TRUE, TRUE, 'system', 'system'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM scheduled_job WHERE key = 'location-trigger-expiry'")
    )
    op.drop_table("location_event")
    op.drop_table("location_trigger")
    op.drop_table("known_place")
