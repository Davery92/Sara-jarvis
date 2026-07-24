"""Singular Sara — canonical intent/attention/action/body tables (§C3/C7/C9/C10).

Consolidates the schema from SINGULAR_SARA_MASTER_PLAN_2026_07_24.md's
backend groundwork: `intent`/`intent_edge` (§C3), `body_capability` (§C7),
`outbound_intent`/`attention_item` (§C9), `action_receipt` (§C10), and
`scheduled_job.singular_class` (§C11).

These tables were originally created via ad-hoc scripts under
`backend/migrations/` (not tracked by Alembic) during same-day
development — this revision is the retroactive, canonical record so a
fresh environment running `alembic upgrade head` gets the same schema this
one already has. Applied here via `stamp`, not `upgrade`, on the shared dev
database (the tables already exist); a fresh database runs this for real.

Revision ID: 121_singular_sara_tables
Revises: 120_bedtime
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "121_singular_sara_tables"
down_revision = "120_bedtime"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # --- §C3: intent graph -------------------------------------------------
    op.create_table(
        "intent",
        sa.Column("intent_id", sa.String(255), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("owner_user_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("priority", sa.String(20)),
        sa.Column("next_step", sa.Text),
        sa.Column("evidence_refs", postgresql.JSONB, server_default="[]"),
        sa.Column("permission_tier", sa.String(30)),
        sa.Column("last_progress_at", sa.DateTime(timezone=True)),
        sa.Column("next_review_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("source_table", sa.String(50)),
        sa.Column("source_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_intent_owner_status", "intent", ["owner_user_id", "status"])
    op.create_index("idx_intent_source", "intent", ["source_table", "source_id"])
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_intent_next_review ON intent (next_review_at) "
        "WHERE next_review_at IS NOT NULL"
    ))

    op.create_table(
        "intent_edge",
        sa.Column("edge_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("from_intent_id", sa.String(255), sa.ForeignKey("intent.intent_id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_intent_id", sa.String(255), sa.ForeignKey("intent.intent_id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("from_intent_id", "to_intent_id", "relation"),
    )
    op.create_index("idx_intent_edge_from", "intent_edge", ["from_intent_id"])
    op.create_index("idx_intent_edge_to", "intent_edge", ["to_intent_id"])

    # --- §C7: body capability registry --------------------------------------
    op.create_table(
        "body_capability",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("version", sa.String(100)),
        sa.Column("capabilities", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("capability_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_body_capability_kind", "body_capability", ["kind"])

    # --- §C9: canonical outbound-intent / attention-item --------------------
    op.create_table(
        "outbound_intent",
        sa.Column("outbound_intent_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("facts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("why_now", sa.Text),
        sa.Column("desired_response", sa.Text),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("interruption_cost", sa.Float),
        sa.Column("channel_eligibility", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("dedupe_key", sa.String(255)),
        sa.Column("source_intent_id", sa.String(255)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_outbound_intent_user", "outbound_intent", ["user_id", "created_at"])

    op.create_table(
        "attention_item",
        sa.Column("attention_item_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("outbound_intent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("outbound_intent.outbound_intent_id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("rendered_text", sa.Text),
        sa.Column("delivered_channels", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_attention_item_outbound", "attention_item", ["outbound_intent_id"])

    # --- §C10: canonical action receipt -------------------------------------
    op.create_table(
        "action_receipt",
        sa.Column("action_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("source_intent_id", sa.String(255)),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("target", sa.Text),
        sa.Column("permission_tier", sa.String(30), nullable=False),
        sa.Column("reversible", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("undo_expires_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("artifact_refs", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("source_table", sa.String(50)),
        sa.Column("source_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_action_receipt_user", "action_receipt", ["user_id", "created_at"])
    op.create_index("idx_action_receipt_status", "action_receipt", ["status"])
    op.create_index("idx_action_receipt_source", "action_receipt", ["source_table", "source_id"])

    # --- §C11: scheduler-diet classification on the existing table ----------
    op.add_column("scheduled_job", sa.Column("singular_class", sa.String(30)))
    op.create_index("idx_scheduled_job_singular_class", "scheduled_job", ["singular_class"])


def downgrade():
    op.drop_index("idx_scheduled_job_singular_class", table_name="scheduled_job")
    op.drop_column("scheduled_job", "singular_class")

    op.drop_index("idx_action_receipt_source", table_name="action_receipt")
    op.drop_index("idx_action_receipt_status", table_name="action_receipt")
    op.drop_index("idx_action_receipt_user", table_name="action_receipt")
    op.drop_table("action_receipt")

    op.drop_index("idx_attention_item_outbound", table_name="attention_item")
    op.drop_table("attention_item")
    op.drop_index("idx_outbound_intent_user", table_name="outbound_intent")
    op.drop_table("outbound_intent")

    op.drop_index("idx_body_capability_kind", table_name="body_capability")
    op.drop_table("body_capability")

    op.drop_index("idx_intent_edge_to", table_name="intent_edge")
    op.drop_index("idx_intent_edge_from", table_name="intent_edge")
    op.drop_table("intent_edge")
    op.drop_index("idx_intent_next_review", table_name="intent")
    op.drop_index("idx_intent_source", table_name="intent")
    op.drop_index("idx_intent_owner_status", table_name="intent")
    op.drop_table("intent")
