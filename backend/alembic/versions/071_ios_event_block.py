"""Blocklist table for suppressed iOS calendar events.

When the user deletes an iOS-synced event in Sara, we add a row here so the
next iOS sync doesn't resurrect it. The user still sees it on their iPhone.

Revision ID: 071_ios_event_block
Revises: 070_reminder_event_link
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "071_ios_event_block"
down_revision = "070_reminder_event_link"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "ios_event_block" in insp.get_table_names():
        return

    op.create_table(
        "ios_event_block",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("ios_event_id", sa.String(), nullable=False),
        sa.Column("ios_calendar_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "ios_event_id"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
    )


def downgrade():
    op.drop_table("ios_event_block")
