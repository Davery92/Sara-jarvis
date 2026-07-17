"""Narrator (REMOVED): trigger-sweep beat — neutralized to a no-op.

Revision ID: 067_narrator_beat
Revises: 066_system_events
Create Date: 2026-05-17

The narrator subsystem was removed. Body neutralized so a fresh database
doesn't seed a `scheduled_job` row pointing at the deleted
`app.tasks.narrator.sweep_triggers` task (which would make celery-beat error).
"""

revision = "067_narrator_beat"
down_revision = "066_system_events"
branch_labels = None
depends_on = None


def upgrade():
    # Narrator removed — no-op. (Originally seeded narrator-sweep-triggers.)
    pass


def downgrade():
    pass
