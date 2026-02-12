"""
Migration: Add policy candidate table (Phase 3 — Cortana Evolution).

Creates:
  - autonomy_policy_candidate: Dream/reflection insights → reviewable policy candidates

Run with:
    python backend/migrations/add_policy_candidates.py
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
            CREATE TABLE IF NOT EXISTS autonomy_policy_candidate (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                candidate_type VARCHAR(50) NOT NULL DEFAULT 'standing_order',
                source VARCHAR(50) NOT NULL DEFAULT 'dream',
                source_id VARCHAR(255),
                status VARCHAR(20) NOT NULL DEFAULT 'new',
                confidence REAL NOT NULL DEFAULT 0.5,
                proposed_config JSONB DEFAULT '{}'::jsonb,
                dedupe_key VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                decided_at TIMESTAMPTZ,
                decided_action VARCHAR(20),
                result_id VARCHAR(255)
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_policy_candidate_user_status
            ON autonomy_policy_candidate (user_id, status, created_at DESC)
        """))

        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_candidate_dedupe
            ON autonomy_policy_candidate (user_id, dedupe_key)
            WHERE dedupe_key IS NOT NULL AND status = 'new'
        """))

        print("[OK] autonomy_policy_candidate table created")

        conn.commit()
        print("\n[DONE] Policy candidates migration complete")


if __name__ == "__main__":
    run_migration()
