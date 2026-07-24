"""
Migration: add `intent` and `intent_edge` tables (SINGULAR_SARA_MASTER_PLAN
§4.3/§C3).

These are the first real, durable step of the intent graph — additive only:
no existing table is touched, nothing reads from these yet except the new
sync/service code in `app.services.intent_graph_service`, and population is
a separate, explicit call (`sync_from_projections`), not a side effect of
this migration.

`source_table`/`source_id` exist so the sync job can do idempotent upserts
keyed to the record each intent was derived from (e.g. "reminder"/"r1")
without duplicating rows on every re-sync.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python migrations/add_intent_graph_tables.py
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
            CREATE TABLE IF NOT EXISTS intent (
                intent_id VARCHAR(255) PRIMARY KEY,
                kind VARCHAR(50) NOT NULL,
                origin VARCHAR(20) NOT NULL,
                owner_user_id VARCHAR(255) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                priority VARCHAR(20),
                next_step TEXT,
                evidence_refs JSONB DEFAULT '[]',
                permission_tier VARCHAR(30),
                last_progress_at TIMESTAMPTZ,
                next_review_at TIMESTAMPTZ,
                outcome TEXT,
                correlation_id VARCHAR(64),
                source_table VARCHAR(50),
                source_id VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: intent")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intent_owner_status
            ON intent (owner_user_id, status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intent_source
            ON intent (source_table, source_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intent_next_review
            ON intent (next_review_at)
            WHERE next_review_at IS NOT NULL
        """))
        print("  Created indexes on intent")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS intent_edge (
                edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                from_intent_id VARCHAR(255) NOT NULL REFERENCES intent(intent_id) ON DELETE CASCADE,
                to_intent_id VARCHAR(255) NOT NULL REFERENCES intent(intent_id) ON DELETE CASCADE,
                relation VARCHAR(30) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (from_intent_id, to_intent_id, relation)
            )
        """))
        print("  Created table: intent_edge")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intent_edge_from ON intent_edge (from_intent_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_intent_edge_to ON intent_edge (to_intent_id)
        """))
        print("  Created indexes on intent_edge")

    print("\nMigration complete: intent + intent_edge")


if __name__ == "__main__":
    print("Running migration: add_intent_graph_tables")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()
    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
