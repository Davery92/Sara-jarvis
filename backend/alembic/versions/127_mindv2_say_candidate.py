"""SARA_MIND_V2 Phase 2 — say_candidate table (§3.5).

Schema only, laid down ahead of the Judge/Compose/Review services so it can
be reviewed and soak-tested independently. Nothing writes to this table
yet (MINDV2_COMPOSE is not wired to any sender) — TTL is mandatory
(`valid_until NOT NULL`) per the plan's mechanical-expiry principle:
"an expired candidate is unreachable by the judge" must be true from the
first row ever inserted, not bolted on later.

Revision ID: 127_mindv2_say_candidate
Revises: 126_mindv2_brief_interest
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "127_mindv2_say_candidate"
down_revision = "126_mindv2_brief_interest"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "say_candidate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("source", sa.String(100), nullable=False),  # which sensor/appraisal emitted this
        sa.Column("kind", sa.String(20), nullable=False),     # inform|followup|prep|alert|retrospective
        sa.Column("topic_entities", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text, nullable=False),        # what could be said, NOT final phrasing
        sa.Column("evidence", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("value_guess", sa.Float),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # pending|judged_send|judged_batch|judged_drop|expired
        sa.Column("judge_reason", sa.Text),
        sa.Column("utterance_id", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(
            "kind IN ('inform','followup','prep','alert','retrospective')",
            name="ck_say_candidate_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','judged_send','judged_batch','judged_drop','expired')",
            name="ck_say_candidate_status",
        ),
    )
    op.create_index("idx_say_candidate_user_status", "say_candidate", ["user_id", "status"])
    # The purge sweep's whole job: find pending rows whose TTL has passed.
    op.create_index(
        "idx_say_candidate_valid_until", "say_candidate", ["valid_until"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("idx_say_candidate_valid_until", table_name="say_candidate")
    op.drop_index("idx_say_candidate_user_status", table_name="say_candidate")
    op.drop_table("say_candidate")
