"""Sara inbox — Phase 4 of the ACS redo (hybrid trigger model).

Revision ID: 060_sara_inbox
Revises: 059_sara_activity_log_focus
Create Date: 2026-05-06

David queues work for Sara via this table; she sees pending items in her
ambient context every think turn, picks them up on her own cadence, completes
or dismisses them. This is the input half of "honest agency": notify_david
is the output, sara_inbox is the input, and she sees both in her own
activity log so the loop is closed and observable from her perspective.
"""
from alembic import op
import sqlalchemy as sa


revision = "060_sara_inbox"
down_revision = "059_sara_activity_log_focus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sara_inbox",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="david_api"),
        sa.Column("urgency", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        # queued | in_progress | done | dismissed
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_summary", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'done', 'dismissed')",
            name="sara_inbox_status_valid",
        ),
        sa.CheckConstraint(
            "urgency IN ('low', 'normal', 'high')",
            name="sara_inbox_urgency_valid",
        ),
    )
    # Daemon's hot path: "what's queued for me right now?"
    op.create_index(
        "ix_sara_inbox_active",
        "sara_inbox",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("status IN ('queued', 'in_progress')"),
    )


def downgrade() -> None:
    op.drop_index("ix_sara_inbox_active", table_name="sara_inbox")
    op.drop_table("sara_inbox")
