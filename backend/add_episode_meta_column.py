"""
Add meta column to episode table

This migration adds the JSONB meta column to the episode table if it doesn't exist.
"""

import os
import psycopg
from psycopg.types.json import Jsonb

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg format
db_url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

def main():
    print("=" * 60)
    print("ADDING EPISODE META COLUMN MIGRATION")
    print("=" * 60)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Check if meta column already exists
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='episode' AND column_name='meta';
            """)

            if cur.fetchone():
                print("✅ Column 'meta' already exists in episode table")
                return

            print("Adding 'meta' column to episode table...")

            # Add meta column as JSONB with default empty object
            cur.execute("""
                ALTER TABLE episode
                ADD COLUMN meta JSONB DEFAULT '{}';
            """)

            conn.commit()
            print("✅ Successfully added 'meta' column to episode table")

            # Verify the column was added
            cur.execute("""
                SELECT column_name, data_type, column_default
                FROM information_schema.columns
                WHERE table_name='episode' AND column_name='meta';
            """)

            result = cur.fetchone()
            if result:
                print(f"   Column: {result[0]}, Type: {result[1]}, Default: {result[2]}")

            # Show count of episodes
            cur.execute("SELECT COUNT(*) FROM episode;")
            count = cur.fetchone()[0]
            print(f"   Total episodes in table: {count}")

if __name__ == "__main__":
    main()
