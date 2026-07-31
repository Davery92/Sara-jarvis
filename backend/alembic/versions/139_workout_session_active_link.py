"""item 2.1 remainder (2026-07-31): session-lifecycle unification.

The calendar-scheduled `workout_session` table and the real-time
`active_workout_session` table (workout_command_service's canonical model)
have been two disconnected worlds — a calendar-triggered workout wrote sets
through raw SQL with none of the coaching/progression/cross-device-conflict
logic the phone/Watch path gets. This column is the pointer that lets a
calendar-originated session hand off to the real v2 session once started,
so `/sessions/{id}/log-set` and `/complete` can delegate to
workout_command_service instead of re-implementing it.

Revision ID: 139_workout_session_active_link
Revises: 138_moment_card
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa


revision = "139_workout_session_active_link"
down_revision = "138_moment_card"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        ALTER TABLE workout_session
        ADD COLUMN IF NOT EXISTS active_session_id VARCHAR(36)
            REFERENCES active_workout_session(id) ON DELETE SET NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_workout_session_active_session
        ON workout_session (active_session_id)
        WHERE active_session_id IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_workout_session_active_session"))
    bind.execute(sa.text("ALTER TABLE workout_session DROP COLUMN IF EXISTS active_session_id"))
