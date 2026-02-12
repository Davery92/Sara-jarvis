"""
Migration: Add attention queue and mission tables (Phase 2 — Cortana Evolution).

Creates:
  - autonomy_attention_item: Persistent proactive inbox for non-urgent items
  - autonomy_mission: Multi-step persistent tasks
  - autonomy_mission_step: Individual steps within missions
  - Extends notification_log: attention_item_id FK

Run with:
    python backend/migrations/add_attention_and_missions.py
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
        # autonomy_attention_item
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS autonomy_attention_item (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                category VARCHAR(50) NOT NULL DEFAULT 'general',
                priority VARCHAR(20) NOT NULL DEFAULT 'normal',
                source VARCHAR(50) NOT NULL DEFAULT 'unified_agent',
                status VARCHAR(20) NOT NULL DEFAULT 'new',
                dedupe_key VARCHAR(255),
                payload JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                read_at TIMESTAMPTZ,
                archived_at TIMESTAMPTZ
            )
        """))

        # Partial unique index for dedup (only active items)
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_attention_dedupe
            ON autonomy_attention_item (user_id, dedupe_key)
            WHERE dedupe_key IS NOT NULL AND status IN ('new', 'sent')
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_attention_user_status
            ON autonomy_attention_item (user_id, status, created_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_attention_priority
            ON autonomy_attention_item (user_id, priority, created_at DESC)
            WHERE status IN ('new', 'sent')
        """))

        print("[OK] autonomy_attention_item table created")

        # ============================
        # autonomy_mission
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS autonomy_mission (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                source VARCHAR(50) NOT NULL DEFAULT 'user',
                state VARCHAR(20) NOT NULL DEFAULT 'pending',
                priority VARCHAR(20) NOT NULL DEFAULT 'normal',
                total_steps INTEGER NOT NULL DEFAULT 0,
                completed_steps INTEGER NOT NULL DEFAULT 0,
                current_step_index INTEGER NOT NULL DEFAULT 0,
                requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
                confirmed_at TIMESTAMPTZ,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mission_user_state
            ON autonomy_mission (user_id, state, created_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mission_active
            ON autonomy_mission (state, updated_at)
            WHERE state IN ('pending', 'running', 'awaiting_confirm')
        """))

        print("[OK] autonomy_mission table created")

        # ============================
        # autonomy_mission_step
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS autonomy_mission_step (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                mission_id UUID NOT NULL REFERENCES autonomy_mission(id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL,
                action_name VARCHAR(255) NOT NULL,
                action_args JSONB DEFAULT '{}'::jsonb,
                description TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                result JSONB,
                error_message TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        # Unique index per mission+step
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_step_unique
            ON autonomy_mission_step (mission_id, step_index)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_mission_step_status
            ON autonomy_mission_step (mission_id, status)
        """))

        print("[OK] autonomy_mission_step table created")

        # ============================
        # Extend notification_log
        # ============================
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'notification_log' AND column_name = 'attention_item_id'
                ) THEN
                    ALTER TABLE notification_log ADD COLUMN attention_item_id UUID
                        REFERENCES autonomy_attention_item(id);
                END IF;
            END $$
        """))

        print("[OK] notification_log extended with attention_item_id")

        conn.commit()
        print("\n[DONE] Attention queue and missions migration complete")


if __name__ == "__main__":
    run_migration()
