"""Add recall_relevance_ema column to episode table for memory recall feedback."""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "").replace("+psycopg", "")


def upgrade():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'episode' AND column_name = 'recall_relevance_ema'
        """))
        if result.fetchone():
            print("recall_relevance_ema column already exists, skipping")
            return

        conn.execute(text("""
            ALTER TABLE episode ADD COLUMN recall_relevance_ema DOUBLE PRECISION DEFAULT 0.5
        """))
        print("Added recall_relevance_ema column to episode table")

        # Also add last_accessed if missing
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'episode' AND column_name = 'last_accessed'
        """))
        if not result.fetchone():
            conn.execute(text("""
                ALTER TABLE episode ADD COLUMN last_accessed TIMESTAMP WITH TIME ZONE
            """))
            print("Added last_accessed column to episode table")


if __name__ == "__main__":
    upgrade()
