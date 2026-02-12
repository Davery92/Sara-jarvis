"""
Migration: Add home_state_summary table for hourly HA aggregations.

Stores one row per hour with aggregated HA event data.
Enables pattern analysis without querying raw event logs.

Run: python backend/migrations/add_home_state_summary.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://sara:sara123@10.185.1.180:5432/sara_hub",
)


def run_migration():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS home_state_summary (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                hour_bucket TIMESTAMP NOT NULL,
                rooms_active JSONB,
                temperature_avg FLOAT,
                lights_on_count INT DEFAULT 0,
                motion_events INT DEFAULT 0,
                door_events INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_home_state_summary_user_hour
            ON home_state_summary (user_id, hour_bucket DESC)
        """))

        # Unique constraint to prevent duplicate hour buckets
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_home_state_summary_unique
            ON home_state_summary (user_id, hour_bucket)
        """))

    print("✅ home_state_summary table created successfully")


if __name__ == "__main__":
    run_migration()
