"""Narrator (REMOVED): tunable cooldown knobs — neutralized to a no-op.

Revision ID: 068_narrator_tunables
Revises: 067_narrator_beat
Create Date: 2026-05-17

The narrator subsystem was removed. Body neutralized so a fresh database
doesn't seed the now-unused narrator cooldown `tunable_setting` rows.
"""

revision = "068_narrator_tunables"
down_revision = "067_narrator_beat"
branch_labels = None
depends_on = None


def upgrade():
    # Narrator removed — no-op. (Originally seeded narrator_* cooldown tunables.)
    pass


def downgrade():
    pass
