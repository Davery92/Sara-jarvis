#!/usr/bin/env python3
"""
Migration script to create the workspace_states table.
This table stores the canvas/workspace state for each user for cross-device sync.
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
                WHERE table_name = 'workspace_states'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            print("workspace_states table already exists")
        else:
            print("Creating workspace_states table...")
            cursor.execute("""
                CREATE TABLE workspace_states (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
                    state_data JSONB DEFAULT '{}',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("Created workspace_states table")

            # Create index on user_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workspace_states_user_id
                ON workspace_states(user_id)
            """)
            print("Created index on user_id")

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
