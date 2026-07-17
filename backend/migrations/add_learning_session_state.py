"""
Migration: Add session state columns to topic_scratchpad table
Enables session continuity for the learning system
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text


def run_migration():
    """Add session_state and last_interaction_at columns to topic_scratchpad"""
    database_url = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Check if columns exist
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'topic_scratchpad'
            AND column_name IN ('session_state', 'last_interaction_at')
        """))
        existing_columns = [row[0] for row in result.fetchall()]

        # Add session_state column if not exists
        if 'session_state' not in existing_columns:
            print("Adding session_state column to topic_scratchpad...")
            conn.execute(text("""
                ALTER TABLE topic_scratchpad
                ADD COLUMN session_state JSONB DEFAULT '{}'::jsonb
            """))
            print("  ✓ session_state column added")
        else:
            print("  - session_state column already exists")

        # Add last_interaction_at column if not exists
        if 'last_interaction_at' not in existing_columns:
            print("Adding last_interaction_at column to topic_scratchpad...")
            conn.execute(text("""
                ALTER TABLE topic_scratchpad
                ADD COLUMN last_interaction_at TIMESTAMP WITH TIME ZONE
            """))
            print("  ✓ last_interaction_at column added")
        else:
            print("  - last_interaction_at column already exists")

        conn.commit()
        print("\nMigration completed successfully!")


if __name__ == "__main__":
    run_migration()
