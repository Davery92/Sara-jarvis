"""
Migration: Add unified heartbeat tables (agent_run_log + notification_log).

Run with:
    python backend/migrations/add_unified_heartbeat.py
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
        # ============================
        # agent_run_log
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_run_log (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                run_duration_ms INTEGER,
                context_summary TEXT,
                actions_taken JSONB DEFAULT '[]'::jsonb,
                notifications_sent JSONB DEFAULT '[]'::jsonb,
                observations TEXT,
                conversation_flags JSONB DEFAULT '[]'::jsonb,
                handoff_note TEXT,
                watching_for TEXT,
                david_state_snapshot JSONB,
                journal_entry_id VARCHAR(255),
                source VARCHAR(50) DEFAULT 'unified_heartbeat',
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        # Indexes for agent_run_log
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_run_log_user_run_at
            ON agent_run_log (user_id, run_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_run_log_recent
            ON agent_run_log (run_at DESC)
        """))

        # ============================
        # notification_log
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                topic VARCHAR(200) NOT NULL,
                category VARCHAR(50) NOT NULL DEFAULT 'general',
                title VARCHAR(500),
                message TEXT,
                priority VARCHAR(20) DEFAULT 'normal',
                source VARCHAR(50) DEFAULT 'unified_heartbeat',
                agent_run_id INTEGER REFERENCES agent_run_log(id),
                cooldown_hours FLOAT DEFAULT 4.0,
                sent BOOLEAN DEFAULT TRUE,
                dedup_blocked BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        # Indexes for notification_log
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_notification_log_topic_dedup
            ON notification_log (user_id, topic, sent_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_notification_log_category
            ON notification_log (user_id, category, sent_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_notification_log_today
            ON notification_log (user_id, sent_at DESC)
        """))

        conn.commit()

    print("Migration complete: agent_run_log and notification_log tables created.")


if __name__ == "__main__":
    run_migration()
