"""Align proactive ORM schema with live proactive tables.

Revision ID: 049_align_proactive_schema
Revises: 048_skill_effectiveness_tracking
Create Date: 2026-02-22
"""

from alembic import op


revision = "049_align_proactive_schema"
down_revision = "048_skill_effectiveness_tracking"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE proactive_suggestion
            ADD COLUMN IF NOT EXISTS category VARCHAR,
            ADD COLUMN IF NOT EXISTS actioned_at TIMESTAMPTZ;
        """
    )

    op.execute(
        """
        ALTER TABLE detected_pattern
            ADD COLUMN IF NOT EXISTS title VARCHAR,
            ADD COLUMN IF NOT EXISTS frequency VARCHAR,
            ADD COLUMN IF NOT EXISTS data_points INTEGER,
            ADD COLUMN IF NOT EXISTS evidence TEXT,
            ADD COLUMN IF NOT EXISTS related_episodes TEXT,
            ADD COLUMN IF NOT EXISTS last_confirmed TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE detected_pattern
            DROP COLUMN IF EXISTS created_at,
            DROP COLUMN IF EXISTS last_confirmed,
            DROP COLUMN IF EXISTS related_episodes,
            DROP COLUMN IF EXISTS evidence,
            DROP COLUMN IF EXISTS data_points,
            DROP COLUMN IF EXISTS frequency,
            DROP COLUMN IF EXISTS title;
        """
    )

    op.execute(
        """
        ALTER TABLE proactive_suggestion
            DROP COLUMN IF EXISTS actioned_at,
            DROP COLUMN IF EXISTS category;
        """
    )
