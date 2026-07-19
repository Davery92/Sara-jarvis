"""Standing-context scratchpad David can dictate (Phase 10C).

A general "pinned context" pad — free text David tells Sara to keep front of
mind ("meal prepped B/L/D this week; smoothie every morning on the drive home").
Injected into EVERY chat + deliberation context so Sara *knows* it, rather than
hoping the retriever surfaces it. Distinct from topic_scratchpad (learning-owned).

Revision ID: 108_scratchpad_entry
Revises: 107_self_audit_beat
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "108_scratchpad_entry"
down_revision = "107_self_audit_beat"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "scratchpad_entry" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "scratchpad_entry",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="other"),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_from", sa.String(32), nullable=False, server_default="chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_scratchpad_user_active", "scratchpad_entry", ["user_id", "cleared"])


def downgrade():
    op.drop_table("scratchpad_entry")
