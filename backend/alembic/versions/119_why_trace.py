"""Why-trace (§3.10) — every interruption explains itself.

The delivery policy already computes the causal chain (triggering context →
sleep sense → ML opinion → channel/timing decision, with the losing options);
it just dropped it. This table persists it so "why did you ping me at 5 AM?"
returns the real chain, not a confabulation — surfaced in chat and the Self page.

(The existing `reasoning_trace` table is for LLM chat-reasoning traces, a
different concept, so this is purpose-built.)

Revision ID: 119_why_trace
Revises: 118_drop_dead_tables
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "119_why_trace"
down_revision = "118_drop_dead_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "action_why_trace",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String, nullable=False, index=True),
        sa.Column("kind", sa.String, nullable=False),          # notification | action
        sa.Column("category", sa.String, nullable=True),
        sa.Column("priority", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True),
        sa.Column("topic", sa.String, nullable=True),
        sa.Column("decision", sa.String, nullable=True),       # deliver | hold | drop
        sa.Column("reason", sa.String, nullable=True),
        sa.Column("chain", postgresql.JSONB, nullable=True),   # full why_trace
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_why_trace_recent", "action_why_trace", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_why_trace_recent", table_name="action_why_trace")
    op.drop_table("action_why_trace")
