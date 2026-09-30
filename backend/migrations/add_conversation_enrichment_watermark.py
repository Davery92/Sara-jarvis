"""Add incremental-enrichment watermark columns to the conversation table.

Episode enrichment used to reprocess every episode in a conversation on every
turn (fire-and-forget, no watermark), which repeatedly reprocessed the whole
conversation and timed out on long ones. These columns let
app.services.episode_enrichment track how far enrichment has progressed so a
turn only enriches the episodes written since the last successful run.
"""

import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
).replace("+asyncpg", "")


COLUMNS = [
    ("enriched_through_episode_id", "TEXT"),
    ("enriched_through_at", "TIMESTAMP WITH TIME ZONE"),
    ("enrichment_status", "TEXT DEFAULT 'idle'"),
    ("enrichment_attempts", "INTEGER DEFAULT 0"),
    ("enrichment_last_error", "TEXT"),
    ("enrichment_updated_at", "TIMESTAMP WITH TIME ZONE"),
]


def upgrade():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        for name, ddl_type in COLUMNS:
            result = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'conversation' AND column_name = :name
            """), {"name": name})
            if result.fetchone():
                print(f"conversation.{name} already exists, skipping")
                continue
            conn.execute(text(f"ALTER TABLE conversation ADD COLUMN {name} {ddl_type}"))
            print(f"Added conversation.{name}")


if __name__ == "__main__":
    upgrade()
