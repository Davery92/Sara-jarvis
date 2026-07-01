"""Blocked flag on sara_interest — David's veto that actually sticks.

Revision ID: 074_interest_blocked
Revises: 073_sara_goal
Create Date: 2026-06-12

Deleting an interest doesn't stop Sara from pursuing it: the next reflection
cycle re-creates the row and the idle-tick seeder starts queueing it again
(see: ActivityPub, daily, for two weeks). A blocked row stays in the table as
a semantic tombstone — its embedding catches rephrasings via the upsert dedup,
so re-adds merge into it and are rejected instead of resurrecting the topic.
Blocked interests are excluded from every read path (ambient context, tool
lists, idle-tick promotion).
"""
from alembic import op


revision = "074_interest_blocked"
down_revision = "073_sara_goal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sara_interest "
        "ADD COLUMN IF NOT EXISTS blocked BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sara_interest DROP COLUMN IF EXISTS blocked")
