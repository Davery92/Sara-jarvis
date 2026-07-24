"""
SUPERSEDED: this table/column is now also tracked by the canonical Alembic revision alembic/versions/121_singular_sara_tables.py — a fresh environment should use `alembic upgrade head`, not this script. Kept only because it's what actually created these objects in the shared dev database on 2026-07-24; this script and the Alembic revision agree on the schema, so re-running this (CREATE ... IF NOT EXISTS) is harmless but redundant.

Migration: add `body_capability` table (SINGULAR_SARA_MASTER_PLAN §4.4/§C7).

"Distinguish VM workshop, `acs-tool-runner`, managed hosts, and Proxmox
sandboxes in body capability records." Additive only — no existing table
touched. Populated by `/api/acs/v2/heartbeat` (the VM workshop row) and by
`app.services.body_capability_service` for other bodies as they report in.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python migrations/add_body_capability_table.py
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
            CREATE TABLE IF NOT EXISTS body_capability (
                name VARCHAR(100) PRIMARY KEY,
                kind VARCHAR(30) NOT NULL,
                version VARCHAR(100),
                capabilities JSONB NOT NULL DEFAULT '[]',
                capability_metadata JSONB NOT NULL DEFAULT '{}',
                last_seen_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: body_capability")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_body_capability_kind ON body_capability (kind)
        """))
        print("  Created index on body_capability")

    print("\nMigration complete: body_capability")


if __name__ == "__main__":
    print("Running migration: add_body_capability_table")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()
    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
