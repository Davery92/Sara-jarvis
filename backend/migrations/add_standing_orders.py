"""
Migration: Add standing_order and action_ledger tables.

Run: python3 backend/migrations/add_standing_orders.py
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
        # Standing orders table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS standing_order (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                trigger_type VARCHAR(50) NOT NULL,
                trigger_config JSONB DEFAULT '{}',
                action_type VARCHAR(50) NOT NULL,
                action_config JSONB DEFAULT '{}',
                source VARCHAR(50) DEFAULT 'user',
                pattern_id INTEGER,
                status VARCHAR(20) DEFAULT 'active',
                last_executed_at TIMESTAMPTZ,
                execution_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        print("  Created table: standing_order")

        # Action ledger for audit trail + undo
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS action_ledger (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                standing_order_id INTEGER REFERENCES standing_order(id),
                action_type VARCHAR(50) NOT NULL,
                action_config JSONB DEFAULT '{}',
                trigger_context JSONB DEFAULT '{}',
                success BOOLEAN DEFAULT TRUE,
                executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                undo_available BOOLEAN DEFAULT FALSE,
                undo_expires_at TIMESTAMPTZ,
                undone BOOLEAN DEFAULT FALSE,
                undone_at TIMESTAMPTZ,
                source VARCHAR(50) DEFAULT 'standing_order'
            )
        """))
        print("  Created table: action_ledger")

        # Indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_standing_order_user_status
            ON standing_order (user_id, status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_ledger_order
            ON action_ledger (standing_order_id, executed_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_ledger_undo
            ON action_ledger (undo_available, undo_expires_at)
            WHERE undo_available = TRUE AND undone = FALSE
        """))
        print("  Created indexes")

    print("\nMigration complete: standing_order + action_ledger")


if __name__ == "__main__":
    run_migration()
