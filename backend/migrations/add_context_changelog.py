"""
Migration: Add context_changelog table for audit logging of unified context changes.

This table is for debugging and Redis recovery only — NOT read on the hot path.

Run: python backend/migrations/add_context_changelog.py
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
        # context_changelog: audit log for field changes (debugging + recovery)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS context_changelog (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                field_name VARCHAR(100) NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source VARCHAR(100),
                changed_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # Index for recovery queries (rebuild snapshot from recent changes)
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_context_changelog_user_time
            ON context_changelog (user_id, changed_at DESC)
        """))

        # Auto-cleanup: partition or TTL via cron (keep 7 days)
        # Not enforced in schema — handled by maintenance task

    print("✅ context_changelog table created successfully")


if __name__ == "__main__":
    run_migration()
