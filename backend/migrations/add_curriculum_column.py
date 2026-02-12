"""
Migration: Add curriculum JSONB column to topic_scratchpad table
Persists LLM-generated learning paths so they survive panel close/reopen.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def run_migration():
    """Add curriculum JSONB column to topic_scratchpad"""
    database_url = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'topic_scratchpad'
            AND column_name = 'curriculum'
        """))
        existing = [row[0] for row in result.fetchall()]

        if 'curriculum' not in existing:
            print("Adding curriculum column to topic_scratchpad...")
            conn.execute(text("""
                ALTER TABLE topic_scratchpad
                ADD COLUMN curriculum JSONB
            """))
            print("  ✓ curriculum column added")
        else:
            print("  - curriculum column already exists")

        conn.commit()
        print("\nMigration completed successfully!")


if __name__ == "__main__":
    run_migration()
