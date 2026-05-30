"""Narrator: system_events table.

Revision ID: 066_system_events
Revises: 065_sara_self_queue_beat
Create Date: 2026-05-17

PR 1 of the narrator module. Stores every System AI utterance (and every
suppressed-but-logged "silent moment") for replay, ticker history, and
audit. The narrator publishes onto the existing EventBus
(SYSTEM_NARRATION_EMITTED); this table is the durable side of that channel.
"""
from alembic import op
import sqlalchemy as sa


revision = "066_system_events"
down_revision = "065_sara_self_queue_beat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_event",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(64), nullable=False),
        # mirrors severity for now; kept as its own column so we can later
        # distinguish event_type ("achievement") from severity ("grudging")
        # without a migration.
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("trigger_name", sa.String(64), nullable=False),
        sa.Column(
            "trigger_context",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("sound", sa.String(64), nullable=True),
        sa.Column(
            "delivered_to",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Silent-praise / suppressed events still get a row so the ticker's
        # "noted, not narrated" panel has something to count.
        sa.Column(
            "suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "severity IN ('roast','observation','achievement','patch_note',"
            "'sponsored','grudging','deflected')",
            name="ck_system_event_severity_valid",
        ),
    )
    op.create_index(
        "ix_system_event_user_created",
        "system_event",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_system_event_trigger_created",
        "system_event",
        ["trigger_name", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_system_event_trigger_created", table_name="system_event")
    op.drop_index("ix_system_event_user_created", table_name="system_event")
    op.drop_table("system_event")
