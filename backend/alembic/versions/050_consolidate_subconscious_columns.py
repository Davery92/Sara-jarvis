"""Consolidate subconscious_state columns from ad-hoc migrations.

Revision ID: 050_subconscious_cols
Revises: 049_align_proactive_schema
Create Date: 2026-02-22
"""

from alembic import op


revision = "050_subconscious_cols"
down_revision = "049_align_proactive_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE subconscious_state
            ADD COLUMN IF NOT EXISTS activity_state VARCHAR(50),
            ADD COLUMN IF NOT EXISTS activity_confidence FLOAT,
            ADD COLUMN IF NOT EXISTS activity_reason TEXT,
            ADD COLUMN IF NOT EXISTS activity_room VARCHAR(100),
            ADD COLUMN IF NOT EXISTS interruptibility_score FLOAT,
            ADD COLUMN IF NOT EXISTS interruptibility_channel VARCHAR(20),
            ADD COLUMN IF NOT EXISTS nudge_morning_eligible BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS nudge_bedtime_eligible BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS nudge_sleep_deficit FLOAT DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS mood_context TEXT,
            ADD COLUMN IF NOT EXISTS in_flow_state BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS focus_intensity FLOAT,
            ADD COLUMN IF NOT EXISTS body_state TEXT,
            ADD COLUMN IF NOT EXISTS body_state_context TEXT,
            ADD COLUMN IF NOT EXISTS has_chatted_today BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS hours_since_wakeup FLOAT,
            ADD COLUMN IF NOT EXISTS is_past_bedtime BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS first_activity_today TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS recent_conversation_digest TEXT;
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE subconscious_state
            DROP COLUMN IF EXISTS recent_conversation_digest,
            DROP COLUMN IF EXISTS last_activity_at,
            DROP COLUMN IF EXISTS first_activity_today,
            DROP COLUMN IF EXISTS is_past_bedtime,
            DROP COLUMN IF EXISTS hours_since_wakeup,
            DROP COLUMN IF EXISTS has_chatted_today,
            DROP COLUMN IF EXISTS body_state_context,
            DROP COLUMN IF EXISTS body_state,
            DROP COLUMN IF EXISTS focus_intensity,
            DROP COLUMN IF EXISTS in_flow_state,
            DROP COLUMN IF EXISTS mood_context,
            DROP COLUMN IF EXISTS nudge_sleep_deficit,
            DROP COLUMN IF EXISTS nudge_bedtime_eligible,
            DROP COLUMN IF EXISTS nudge_morning_eligible,
            DROP COLUMN IF EXISTS interruptibility_channel,
            DROP COLUMN IF EXISTS interruptibility_score,
            DROP COLUMN IF EXISTS activity_room,
            DROP COLUMN IF EXISTS activity_reason,
            DROP COLUMN IF EXISTS activity_confidence,
            DROP COLUMN IF EXISTS activity_state;
        """
    )
