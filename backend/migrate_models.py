#!/usr/bin/env python3
"""
Migration script to create the models_3d table.
This table stores metadata for 3D models uploaded by users.
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
                WHERE table_name = 'models_3d'
            )
        """)
        exists = cursor.fetchone()[0]

        if exists:
            print("models_3d table already exists")
        else:
            print("Creating models_3d table...")
            cursor.execute("""
                CREATE TABLE models_3d (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    filename VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    file_format VARCHAR(20) NOT NULL,
                    minio_key VARCHAR(512) NOT NULL,
                    file_size BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("Created models_3d table")

            # Create index on user_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_models_3d_user_id
                ON models_3d(user_id)
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
