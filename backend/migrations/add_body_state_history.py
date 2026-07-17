"""
Migration: Add body_state_history table for trend analysis.

Stores one row per subconscious cycle (~288/day at 5-min intervals).
Enables: "You've been stressed all afternoon" and trend-based check-ins.

Run: python backend/migrations/add_body_state_history.py
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
            CREATE TABLE IF NOT EXISTS body_state_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                alertness FLOAT,
                stress_load FLOAT,
                blood_sugar FLOAT,
                circadian_phase VARCHAR(30),
                energy_level FLOAT,
                mood VARCHAR(50),
                in_flow_state BOOLEAN DEFAULT FALSE,
                activity_state VARCHAR(30),
                recorded_at TIMESTAMP DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_body_state_history_user_time
            ON body_state_history (user_id, recorded_at DESC)
        """))

        # Partition-friendly index for cleanup queries
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_body_state_history_recorded
            ON body_state_history (recorded_at)
        """))

    print("✅ body_state_history table created successfully")


if __name__ == "__main__":
    run_migration()
