"""
Migration: Add notification outcome tracking columns to notification_log.

Tracks whether David saw/tapped/dismissed notifications so the heartbeat
agent can adapt check-in frequency.

Run: python backend/migrations/add_notification_outcomes.py
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
        # Add outcome tracking columns
        for col, coltype in [
            ("seen_at", "TIMESTAMP"),
            ("outcome", "VARCHAR(50)"),  # opened_chat, dismissed, no_response
            ("response_time_seconds", "INTEGER"),
        ]:
            try:
                conn.execute(text(f"""
                    ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS {col} {coltype}
                """))
            except Exception:
                pass  # Column may already exist

    print("✅ notification_log outcome columns added successfully")


if __name__ == "__main__":
    run_migration()
