"""
Add app_settings table for persistent configuration storage

This migration creates a key-value settings table to persist runtime configuration
changes made through the settings UI, so they survive backend restarts.
"""

import os
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg format
if DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

def run_migration():
    """Create app_settings table for persistent configuration"""

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            print("Creating app_settings table...")

            # Create app_settings table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by VARCHAR(255)
                )
            """)

            conn.commit()
            print("Successfully created app_settings table")

            # Verify the table was created
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'app_settings'
                ORDER BY ordinal_position
            """)

            columns = cur.fetchall()
            print("\nColumn verification:")
            for col in columns:
                print(f"  {col[0]}: {col[1]}")

if __name__ == "__main__":
    print("Running migration: add_app_settings_table")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()

    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
