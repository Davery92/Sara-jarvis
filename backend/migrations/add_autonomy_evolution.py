"""
Migration: Add autonomy evolution tables (Phase 0 — Action Tracing).

Creates:
  - autonomy_action_trace: Every autonomous action gets a trace record
  - Extends agent_run_log: run_uuid, plan_summary, execution_summary, quiet_mode_active

Retention policy (enforced by autonomy_retention_cleanup Celery task):
  - autonomy_action_trace: 90 days
  - autonomy_attention_item: 30 days archived, 7 days stale new (Phase 2)
  - autonomy_mission: 180 days terminal states (Phase 2)
  - autonomy_policy_candidate: 30 days decided, 14 days auto-expire new (Phase 3)

Run with:
    python backend/migrations/add_autonomy_evolution.py
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
        # autonomy_action_trace
        # ============================
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS autonomy_action_trace (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                run_uuid UUID,
                run_id INTEGER REFERENCES agent_run_log(id),
                user_id VARCHAR(255) NOT NULL,
                source VARCHAR(50) NOT NULL DEFAULT 'unified_agent',
                action_name VARCHAR(255) NOT NULL,
                action_args JSONB,
                risk_tier SMALLINT NOT NULL DEFAULT 0,
                decision VARCHAR(20) NOT NULL DEFAULT 'allow',
                decision_reason TEXT,
                simulation JSONB,
                result JSONB,
                success BOOLEAN NOT NULL DEFAULT TRUE,
                error_message TEXT,
                step_index INTEGER NOT NULL DEFAULT 0,
                idempotency_key VARCHAR(255),
                duration_ms INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        # Indexes for autonomy_action_trace
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_trace_run_uuid
            ON autonomy_action_trace (run_uuid)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_trace_user_created
            ON autonomy_action_trace (user_id, created_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_trace_source
            ON autonomy_action_trace (source, created_at DESC)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_trace_action_name
            ON autonomy_action_trace (action_name, created_at DESC)
        """))

        # Unique index for idempotency
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_action_trace_idempotency
            ON autonomy_action_trace (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """))

        # Retention index (for cleanup task)
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_trace_retention
            ON autonomy_action_trace (created_at)
            WHERE created_at < NOW() - INTERVAL '90 days'
        """))

        print("[OK] autonomy_action_trace table created")

        # ============================
        # Extend agent_run_log
        # ============================
        # Add run_uuid column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_run_log' AND column_name = 'run_uuid'
                ) THEN
                    ALTER TABLE agent_run_log ADD COLUMN run_uuid UUID;
                END IF;
            END $$
        """))

        # Add plan_summary column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_run_log' AND column_name = 'plan_summary'
                ) THEN
                    ALTER TABLE agent_run_log ADD COLUMN plan_summary JSONB;
                END IF;
            END $$
        """))

        # Add execution_summary column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_run_log' AND column_name = 'execution_summary'
                ) THEN
                    ALTER TABLE agent_run_log ADD COLUMN execution_summary JSONB;
                END IF;
            END $$
        """))

        # Add quiet_mode_active column
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'agent_run_log' AND column_name = 'quiet_mode_active'
                ) THEN
                    ALTER TABLE agent_run_log ADD COLUMN quiet_mode_active BOOLEAN DEFAULT FALSE;
                END IF;
            END $$
        """))

        # Index on run_uuid for trace linkage
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_run_log_run_uuid
            ON agent_run_log (run_uuid)
            WHERE run_uuid IS NOT NULL
        """))

        print("[OK] agent_run_log extended with run_uuid, plan_summary, execution_summary, quiet_mode_active")

        conn.commit()
        print("\n[DONE] Autonomy evolution migration complete")


if __name__ == "__main__":
    run_migration()
