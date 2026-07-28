"""SARA_MIND_V2 Phase 1 — World Brief + Interest Model tables (§3.1/§3.2).

The World Brief is "one continuously-maintained document" (current state,
one row per user) plus an append-only patch log for debugging ("every
patch logs source + evidence" — §3.1). It is written only via
`brief_patch()` operations, never free rewrites, so the log doubles as the
audit trail for "why does the brief say X".

The Interest Model is the same shape for a different document: "what David
cares about right now" (§3.2), versioned so nightly diff proposals and
David's own edits are both recoverable, not silently overwritten.

Both are per-user singleton-current + history, matching the `world_brief`
row a Redis cache fronts (renderer output) and `interest_model` a lighter
read (rendered directly into prompts, no cache needed at this scale).

Revision ID: 126_mindv2_brief_interest
Revises: 125_flexible_workout_sets
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "126_mindv2_brief_interest"
down_revision = "125_flexible_workout_sets"
branch_labels = None
depends_on = None


def upgrade():
    # --- World Brief: current row per user ---------------------------------
    op.create_table(
        "world_brief",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("sections", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # --- World Brief: append-only patch log (debugging / why-chain) --------
    op.create_table(
        "world_brief_patch_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("op", sa.String(20), nullable=False),       # add|update|close|move
        sa.Column("section", sa.String(50), nullable=False),  # happened|now_today|ahead|open_loops|comms|body_training|health_deltas|sara_state
        sa.Column("item_key", sa.String(200)),
        sa.Column("content", postgresql.JSONB),
        sa.Column("source", sa.String(100), nullable=False),  # which sensor/appraisal/maintainer sweep wrote this
        sa.Column("evidence", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_world_brief_patch_log_user_created", "world_brief_patch_log", ["user_id", "created_at"])
    op.create_index("idx_world_brief_patch_log_section", "world_brief_patch_log", ["user_id", "section"])

    # --- Interest Model: current row per user -------------------------------
    op.create_table(
        "interest_model",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("content", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # --- Interest Model: versions (nightly diffs, chat-verb edits, seed) ---
    op.create_table(
        "interest_model_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("changed_by", sa.String(50), nullable=False),  # david_chat|david_settings|nightly_diff|seed
        sa.Column("change_note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_interest_model_version_user", "interest_model_version", ["user_id", "version"])


def downgrade():
    op.drop_index("idx_interest_model_version_user", table_name="interest_model_version")
    op.drop_table("interest_model_version")
    op.drop_table("interest_model")

    op.drop_index("idx_world_brief_patch_log_section", table_name="world_brief_patch_log")
    op.drop_index("idx_world_brief_patch_log_user_created", table_name="world_brief_patch_log")
    op.drop_table("world_brief_patch_log")
    op.drop_table("world_brief")
