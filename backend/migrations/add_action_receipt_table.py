"""
SUPERSEDED: this table/column is now also tracked by the canonical Alembic revision alembic/versions/121_singular_sara_tables.py — a fresh environment should use `alembic upgrade head`, not this script. Kept only because it's what actually created these objects in the shared dev database on 2026-07-24; this script and the Alembic revision agree on the schema, so re-running this (CREATE ... IF NOT EXISTS) is harmless but redundant.

Migration: add the expanded `action_receipt` table (SINGULAR_SARA_MASTER_
PLAN §4.7/§C10).

Additive only — does not touch or replace the existing `action_ledger`
table (which stays authoritative for standing-order undo). This is a
canonical, cross-action-type shadow record: every material action gets one
row here regardless of which subsystem executed it, with a permission tier
and a status that can be `completed`, `partial`, `blocked`, `failed`, or
`cancelled` — never a bare boolean that could hide a partial outcome.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python migrations/add_action_receipt_table.py
"""

import os

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub",
)


def run_migration():
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS action_receipt (
                action_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                source_intent_id VARCHAR(255),
                action_type VARCHAR(100) NOT NULL,
                target TEXT,
                permission_tier VARCHAR(30) NOT NULL,
                reversible BOOLEAN NOT NULL DEFAULT FALSE,
                undo_expires_at TIMESTAMPTZ,
                idempotency_key VARCHAR(255),
                status VARCHAR(20) NOT NULL,
                evidence_refs JSONB NOT NULL DEFAULT '[]',
                artifact_refs JSONB NOT NULL DEFAULT '[]',
                executed_at TIMESTAMPTZ,
                correlation_id VARCHAR(64),
                source_table VARCHAR(50),
                source_id VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: action_receipt")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_receipt_user ON action_receipt (user_id, created_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_receipt_status ON action_receipt (status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_action_receipt_source ON action_receipt (source_table, source_id)
        """))
        print("  Created indexes")

    print("\nMigration complete: action_receipt")


if __name__ == "__main__":
    print("Running migration: add_action_receipt_table")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()
    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
