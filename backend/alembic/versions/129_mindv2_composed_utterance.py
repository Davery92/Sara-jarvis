"""SARA_MIND_V2 Phase 2 — composed_utterance table (§3.7).

Compose writes a ComposedUtterance{text, refs, urgency, slot} for a
judge-approved (judged_send) candidate; Review then approves/edits/kills
it. SHADOW MODE: this table is written for inspection — delivery does not
read it, nothing is sent from here. This is the schema Phase 2's real
cutover will eventually point delivery at ("the delivery layer accepts
only ComposedUtterance objects").

Revision ID: 129_mindv2_composed_utterance
Revises: 128_mindv2_commitment
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "129_mindv2_composed_utterance"
down_revision = "128_mindv2_commitment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "composed_utterance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("say_candidate.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("refs", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("urgency", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("slot", sa.String(20)),  # null=immediate, else morning|evening
        sa.Column("review_verdict", sa.String(10), nullable=False),  # approve|edit|kill
        sa.Column("review_reason", sa.Text),
        sa.Column("final_text", sa.Text),  # populated for approve/edit, NULL for kill
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("review_verdict IN ('approve','edit','kill')", name="ck_composed_utterance_verdict"),
    )
    op.create_index("idx_composed_utterance_candidate", "composed_utterance", ["candidate_id"])
    op.create_index("idx_composed_utterance_user_created", "composed_utterance", ["user_id", "created_at"])


def downgrade():
    op.drop_index("idx_composed_utterance_user_created", table_name="composed_utterance")
    op.drop_index("idx_composed_utterance_candidate", table_name="composed_utterance")
    op.drop_table("composed_utterance")
