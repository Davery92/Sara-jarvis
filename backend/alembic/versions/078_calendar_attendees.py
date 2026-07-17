"""Calendar attendees + organizer — Phase 5 of PHENOMENAL_ASSISTANT_PLAN.md.

Revision ID: 078_calendar_attendees
Revises: 077_person_table
Create Date: 2026-07-02

calendar_event had no attendee data at all — the June audit's "no calendar
ownership reasoning" gap and the missing meetings-as-people-interaction
inflow both trace back to this. iOS EventKit sync (ios-app) will populate
attendees going forward; no backfill.

See app/routes/calendar_events.py, app/services/calendar_prep.py,
ios-app/src/services/iosCalendarSync.ts.
"""
from alembic import op


revision = "078_calendar_attendees"
down_revision = "077_person_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_event ADD COLUMN IF NOT EXISTS attendees jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE calendar_event ADD COLUMN IF NOT EXISTS organizer varchar(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_event DROP COLUMN IF EXISTS organizer")
    op.execute("ALTER TABLE calendar_event DROP COLUMN IF EXISTS attendees")
