#!/usr/bin/env python3
"""
Migration script to add calendar_event table
"""
from sqlalchemy import create_engine, text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

def main():
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Create calendar_event table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS calendar_event (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                location TEXT DEFAULT '',
                all_day BOOLEAN DEFAULT FALSE,
                reminder_minutes INTEGER,
                is_completed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Create indexes for better query performance
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_calendar_event_user_id ON calendar_event(user_id)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_calendar_event_start_time ON calendar_event(start_time)
        """))

        conn.commit()
        print("✓ Successfully created calendar_event table")

if __name__ == "__main__":
    main()
