"""Narrator (REMOVED): system_events table — neutralized to a no-op.

Revision ID: 066_system_events
Revises: 065_sara_self_queue_beat
Create Date: 2026-05-17

The narrator subsystem was removed. This migration is kept (revision IDs
066–069 are mid-chain; 070+ depend on them) but its body is now a no-op so a
fresh database rebuild doesn't recreate the orphaned `system_event` table.
"""

revision = "066_system_events"
down_revision = "065_sara_self_queue_beat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Narrator removed — no-op. (Originally created the `system_event` table.)
    pass


def downgrade() -> None:
    pass
