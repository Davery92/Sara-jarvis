"""
Migration: add `outbound_intent` and `attention_item` tables
(SINGULAR_SARA_MASTER_PLAN §4.6/§C9).

Additive only. Populated as a SHADOW RECORD of decisions the existing
`send_notification()` pipeline already makes — it does not decide anything
itself yet, and does not change what gets sent, to whom, or when. See
`app.services.attention_shadow_recorder`.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python migrations/add_attention_tables.py
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
            CREATE TABLE IF NOT EXISTS outbound_intent (
                outbound_intent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id VARCHAR(255) NOT NULL,
                subject TEXT NOT NULL,
                facts JSONB NOT NULL DEFAULT '[]',
                why_now TEXT,
                desired_response TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                interruption_cost REAL,
                channel_eligibility JSONB NOT NULL DEFAULT '[]',
                dedupe_key VARCHAR(255),
                source_intent_id VARCHAR(255),
                correlation_id VARCHAR(64),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: outbound_intent")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attention_item (
                attention_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                outbound_intent_id UUID NOT NULL REFERENCES outbound_intent(outbound_intent_id) ON DELETE CASCADE,
                decision VARCHAR(30) NOT NULL,
                rendered_text TEXT,
                delivered_channels JSONB NOT NULL DEFAULT '[]',
                delivered_at TIMESTAMPTZ,
                acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
                correlation_id VARCHAR(64),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        print("  Created table: attention_item")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_outbound_intent_user
            ON outbound_intent (user_id, created_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_attention_item_outbound
            ON attention_item (outbound_intent_id)
        """))
        print("  Created indexes")

    print("\nMigration complete: outbound_intent + attention_item")


if __name__ == "__main__":
    print("Running migration: add_attention_tables")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()
    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
