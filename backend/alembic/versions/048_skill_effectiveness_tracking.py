"""Add skill effectiveness tracking columns to candidate_skill

Revision ID: 048_skill_effectiveness_tracking
Revises: 047_notification_feedback
Create Date: 2026-02-20

Adds:
- times_used: How many times this skill was injected as context for a task
- times_succeeded: How many of those tasks completed successfully
"""
from alembic import op


revision = "048_skill_effectiveness_tracking"
down_revision = "047_notification_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE candidate_skill
            ADD COLUMN IF NOT EXISTS times_used INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS times_succeeded INTEGER NOT NULL DEFAULT 0;
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE candidate_skill
            DROP COLUMN IF EXISTS times_used,
            DROP COLUMN IF EXISTS times_succeeded;
        """
    )
