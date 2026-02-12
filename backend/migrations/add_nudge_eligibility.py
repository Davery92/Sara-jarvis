"""
Migration: Add nudge eligibility columns to subconscious_state table.

These flags let the heartbeat agent see what nudge conditions the
subconscious has detected, so it can craft personalized messages.

Run: python3 backend/migrations/add_nudge_eligibility.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)


def run_migration():
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        columns_to_add = [
            ("nudge_morning_eligible", "BOOLEAN DEFAULT false"),
            ("nudge_bedtime_eligible", "BOOLEAN DEFAULT false"),
            ("nudge_sleep_deficit", "FLOAT DEFAULT 0.0"),
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(
                    f"ALTER TABLE subconscious_state ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                ))
                print(f"  Added column: subconscious_state.{col_name} ({col_type})")
            except Exception as e:
                print(f"  Column {col_name} may already exist: {e}")

    print("Migration complete: nudge eligibility columns added")


if __name__ == "__main__":
    run_migration()
