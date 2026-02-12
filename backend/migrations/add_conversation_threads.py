"""
Migration: Add followup_thread table for tracking follow-up topics.

Run with:
    python backend/migrations/add_conversation_threads.py
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sara:sara123@10.185.1.180:5432/sara_hub"
    )
    return create_engine(database_url)


def run_migration():
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS followup_thread (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                topic TEXT NOT NULL,
                topic_category VARCHAR(50),
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                follow_up_after TIMESTAMPTZ,
                follow_up_before TIMESTAMPTZ,
                last_mentioned_at TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ,
                mention_count INTEGER DEFAULT 0,
                max_mentions INTEGER DEFAULT 3,
                david_response VARCHAR(20),
                original_context TEXT,
                suggested_followup TEXT,
                priority FLOAT DEFAULT 0.5,
                source VARCHAR(50) DEFAULT 'chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_followup_thread_user_open
            ON followup_thread (user_id, status)
            WHERE status = 'open'
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_followup_thread_window
            ON followup_thread (follow_up_after, follow_up_before)
            WHERE status = 'open'
        """))

        conn.commit()
        print("✓ followup_thread table created")


if __name__ == "__main__":
    run_migration()
