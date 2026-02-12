"""
Migration: Add control plane columns (Phase 1 — Cortana Evolution).

Extends:
  - standing_order: confidence, risk_tier, auto_pause_reason, last_conflict_at
  - automation_task: origin, risk_tier, requires_confirmation

Run with:
    python backend/migrations/add_control_plane_columns.py
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
        # Extend standing_order
        # ============================
        for col, definition in [
            ("confidence", "REAL DEFAULT 0.7"),
            ("risk_tier", "SMALLINT DEFAULT 1"),
            ("auto_pause_reason", "TEXT"),
            ("last_conflict_at", "TIMESTAMPTZ"),
        ]:
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'standing_order' AND column_name = '{col}'
                    ) THEN
                        ALTER TABLE standing_order ADD COLUMN {col} {definition};
                    END IF;
                END $$
            """))
        print("[OK] standing_order extended with confidence, risk_tier, auto_pause_reason, last_conflict_at")

        # ============================
        # Extend automation_task
        # ============================
        for col, definition in [
            ("origin", "VARCHAR(32) DEFAULT 'user'"),
            ("risk_tier", "SMALLINT DEFAULT 1"),
            ("requires_confirmation", "BOOLEAN DEFAULT FALSE"),
        ]:
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'automation_task' AND column_name = '{col}'
                    ) THEN
                        ALTER TABLE automation_task ADD COLUMN {col} {definition};
                    END IF;
                END $$
            """))
        print("[OK] automation_task extended with origin, risk_tier, requires_confirmation")

        conn.commit()
        print("\n[DONE] Control plane columns migration complete")


if __name__ == "__main__":
    run_migration()
