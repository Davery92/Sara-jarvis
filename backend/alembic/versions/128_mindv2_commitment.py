"""SARA_MIND_V2 Phase 4 — sara_commitment table (§3.9).

Replaces `sara_goal`, which is already dead code (0 references anywhere in
the backend, 3 rows in its lifetime per the audit) — this is a clean
introduction, not a data migration. Created by the judge ("I'll watch X and
tell you when Y"), rendered in the brief's OPEN LOOPS, closed explicitly;
closure itself becomes a say_candidate so "it woke up" gets said, not just
silently marked done.

Revision ID: 128_mindv2_commitment
Revises: 127_mindv2_say_candidate
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "128_mindv2_commitment"
down_revision = "127_mindv2_say_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sara_commitment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_from", sa.String(100), nullable=False),  # judge|chat|appraisal|manual
        sa.Column("trigger_at", sa.DateTime(timezone=True)),        # optional due time
        sa.Column("trigger_description", sa.Text),                  # optional non-time trigger
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),  # open|done|dropped
        sa.Column("closure_note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open','done','dropped')", name="ck_sara_commitment_status"),
    )
    op.create_index("idx_sara_commitment_user_status", "sara_commitment", ["user_id", "status"])


def downgrade():
    op.drop_index("idx_sara_commitment_user_status", table_name="sara_commitment")
    op.drop_table("sara_commitment")
