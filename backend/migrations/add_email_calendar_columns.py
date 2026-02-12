"""
Migration: Add calendar event tracking columns to email table

This adds columns to track when Sara creates calendar events from meeting emails:
- has_meeting: Boolean flag if email contains a meeting
- calendar_event_id: The CalendarEvent.id if one was created
- calendar_event_created_at: When the event was created
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)


def run_migration():
    """Add calendar tracking columns to email table."""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Check if columns already exist
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'email' AND column_name = 'has_meeting'
        """))

        if result.fetchone():
            print("Migration already applied - calendar columns exist")
            return

        print("Adding calendar tracking columns to email table...")

        # Add the new columns
        conn.execute(text("""
            ALTER TABLE email
            ADD COLUMN IF NOT EXISTS has_meeting BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR,
            ADD COLUMN IF NOT EXISTS calendar_event_created_at TIMESTAMP WITH TIME ZONE
        """))

        conn.commit()
        print("Migration complete - calendar tracking columns added")


if __name__ == "__main__":
    run_migration()
