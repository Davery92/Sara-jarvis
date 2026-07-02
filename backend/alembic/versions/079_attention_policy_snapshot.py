"""Attention policy snapshot — weekly theta history for the learning-felt digest.

Revision ID: 079_attention_policy_snapshot
Revises: 078_calendar_attendees
Create Date: 2026-07-02

The theta table (attention_policy) moves invisibly week to week. This tiny
table is written once a week by the digest job (app/tasks/learning_digest.py)
so the god view can render a theta sparkline and the digest can diff
"where did I back off / lean in this week" (Phase 6 of
PHENOMENAL_ASSISTANT_PLAN.md).
"""
from alembic import op


revision = "079_attention_policy_snapshot"
down_revision = "078_calendar_attendees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attention_policy_snapshot (
            id          varchar PRIMARY KEY,
            user_id     varchar NOT NULL,
            domain      varchar NOT NULL,
            context     varchar NOT NULL,
            threshold   double precision NOT NULL,
            captured_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attention_policy_snapshot_cell "
        "ON attention_policy_snapshot (user_id, domain, context, captured_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attention_policy_snapshot_cell")
    op.execute("DROP TABLE IF EXISTS attention_policy_snapshot")
