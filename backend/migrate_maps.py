#!/usr/bin/env python3
"""
Migration script to create the maps table.
This table stores mindmaps/flowcharts for the workspace canvas.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sara:sara123@10.185.1.180:5432/sara_hub")


def migrate():
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    try:
        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'maps'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            print("maps table already exists")
        else:
            print("Creating maps table...")
            cursor.execute("""
                CREATE TABLE maps (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    map_data JSONB DEFAULT '{"nodes": [], "edges": []}',
                    is_readonly BOOLEAN DEFAULT FALSE,
                    import_source VARCHAR(50),
                    import_raw TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("Created maps table")

            # Create index on user_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_maps_user_id
                ON maps(user_id)
            """)
            print("Created index on user_id")

            # Create index on name for searching
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_maps_name
                ON maps(name)
            """)
            print("Created index on name")

        conn.commit()
        print("Migration completed successfully")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    migrate()
