"""
Add body weight tracking to daily recovery log

This migration adds body_weight and weight_unit columns to the daily_recovery_log table
to enable tracking of body weight alongside recovery metrics.
"""

import os
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub")

# Convert SQLAlchemy URL to psycopg format
if DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

def run_migration():
    """Add body_weight and weight_unit columns to daily_recovery_log table"""

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            print("Adding body_weight columns to daily_recovery_log table...")

            # Add body_weight column (decimal with 2 decimal places, e.g., 185.5 lbs)
            cur.execute("""
                ALTER TABLE daily_recovery_log
                ADD COLUMN IF NOT EXISTS body_weight DECIMAL(5,2)
            """)

            # Add weight_unit column (default 'lbs', can be 'lbs' or 'kg')
            cur.execute("""
                ALTER TABLE daily_recovery_log
                ADD COLUMN IF NOT EXISTS weight_unit VARCHAR(3) DEFAULT 'lbs'
            """)

            conn.commit()
            print("Successfully added body_weight and weight_unit columns")

            # Verify the columns were added
            cur.execute("""
                SELECT column_name, data_type, character_maximum_length, column_default
                FROM information_schema.columns
                WHERE table_name = 'daily_recovery_log'
                AND column_name IN ('body_weight', 'weight_unit')
                ORDER BY column_name
            """)

            columns = cur.fetchall()
            print("\nColumn verification:")
            for col in columns:
                print(f"  {col[0]}: {col[1]}" +
                     (f"({col[2]})" if col[2] else "") +
                     (f" DEFAULT {col[3]}" if col[3] else ""))

if __name__ == "__main__":
    print("Running migration: add_body_weight_to_recovery")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()

    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
