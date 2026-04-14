"""
Migrate data from legacy 'event' table to 'calendar_event' table.

Maps columns:
  event.starts_at -> calendar_event.start_time
  event.ends_at -> calendar_event.end_time
  event.{id,user_id,title,location,description} -> same columns
  Sets source='sara' for migrated rows.

Skips rows that already exist (matching user_id + title + start_time).
Does NOT delete the old table — just copies data.
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "").replace("+psycopg", "")


def upgrade():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        # Check both tables exist
        result = conn.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE tablename IN ('event', 'calendar_event')
        """))
        tables = {r[0] for r in result.fetchall()}
        if 'event' not in tables:
            print("'event' table does not exist, nothing to migrate")
            return
        if 'calendar_event' not in tables:
            print("'calendar_event' table does not exist, cannot migrate")
            return

        # Copy rows that don't already exist in calendar_event
        result = conn.execute(text("""
            INSERT INTO calendar_event (id, user_id, title, description, start_time, end_time, location, source, created_at, updated_at)
            SELECT
                e.id, e.user_id, e.title, e.description,
                e.starts_at AS start_time,
                e.ends_at AS end_time,
                e.location,
                'sara' AS source,
                e.created_at, e.updated_at
            FROM event e
            WHERE NOT EXISTS (
                SELECT 1 FROM calendar_event ce
                WHERE ce.user_id = e.user_id
                  AND ce.title = e.title
                  AND ce.start_time = e.starts_at
            )
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """))
        migrated = result.fetchall()
        print(f"Migrated {len(migrated)} event(s) from 'event' to 'calendar_event'")


if __name__ == "__main__":
    upgrade()
