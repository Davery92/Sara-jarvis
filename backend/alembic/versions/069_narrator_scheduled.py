"""Narrator (REMOVED): patch-notes / recap / sponsored beats — neutralized.

Revision ID: 069_narrator_scheduled
Revises: 068_narrator_tunables
Create Date: 2026-05-17

The narrator subsystem was removed. Body neutralized so a fresh database
doesn't seed `scheduled_job` rows pointing at deleted
`app.tasks.narrator.*` tasks (which would make celery-beat error).
"""

revision = "069_narrator_scheduled"
down_revision = "068_narrator_tunables"
branch_labels = None
depends_on = None


def upgrade():
    # Narrator removed — no-op. (Originally seeded daily_patch_notes,
    # weekly_recap, and sponsored_interjection scheduled jobs.)
    pass


def downgrade():
    pass
