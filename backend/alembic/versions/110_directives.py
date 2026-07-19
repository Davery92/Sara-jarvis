"""Directives — corrections with permanent teeth (Phase 12B).

Sara's own CLAUDE.md, authored by David through conversation. "Never bring up
ActivityPub." "Always use ET." "Don't ping me before 9 on weekends." Stored as
first-class RULES (not episodes, not facts), ALWAYS injected into every chat,
deliberation, and agent prompt. This is the mechanism that would have made the
JIT correction stick the first time.

Revision ID: 110_directives
Revises: 109_day_type_override
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "110_directives"
down_revision = "109_day_type_override"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "directive" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "directive",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="general"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_directive_user_active", "directive", ["user_id", "active"])


def downgrade():
    op.drop_table("directive")
