"""Add origin column to research_plan and drop hardcoded model_id default.

Revision ID: 054_research_plan_origin
Revises: 053_acs_session_mlx_default
Create Date: 2026-05-02

- Adds `origin` enum-like column ('david_chat' | 'acs_autonomous' | 'sara_internal')
  so ACS can defer to live David-initiated research.
- Drops the hardcoded `model_id='Qwen3.5-27B'` default. The research executor
  now resolves the model from whatever is loaded on the configured LLM endpoint
  (BG_LLM_PRIMARY_URL / research_llm_url), so a stale literal in the column
  default just causes drift.
- Backfills `origin` for existing rows: created_by='sara' → 'sara_internal'
  (best guess; existing rows predate the david_chat distinction).
"""
from alembic import op
import sqlalchemy as sa


revision = "054_research_plan_origin"
down_revision = "053_acs_session_mlx_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add origin column (nullable initially so backfill is clean)
    op.execute(
        """
        ALTER TABLE research_plan
        ADD COLUMN IF NOT EXISTS origin VARCHAR(32)
        """
    )

    # Backfill: anything created_by='sara' was Sara's internal/autonomous loop
    op.execute(
        """
        UPDATE research_plan
        SET origin = 'sara_internal'
        WHERE origin IS NULL
        """
    )

    # Make NOT NULL with default for new rows
    op.execute(
        """
        ALTER TABLE research_plan
        ALTER COLUMN origin SET DEFAULT 'sara_internal',
        ALTER COLUMN origin SET NOT NULL
        """
    )

    # Index for the ACS deferral check (find active david_chat plans)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_research_plan_origin_status
        ON research_plan (origin, status)
        """
    )

    # Drop the stale hardcoded model_id default
    op.execute(
        """
        ALTER TABLE research_plan
        ALTER COLUMN model_id DROP DEFAULT
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_research_plan_origin_status")
    op.execute("ALTER TABLE research_plan DROP COLUMN IF EXISTS origin")
    op.execute(
        "ALTER TABLE research_plan ALTER COLUMN model_id SET DEFAULT 'Qwen3.5-27B'"
    )
