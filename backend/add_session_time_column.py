"""
Add session_time column to workout_log table
"""
import psycopg
from datetime import datetime

DATABASE_URL = "postgresql://sara:sara123@10.185.1.180:5432/sara_hub"

def migrate():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Add session_time column (timestamp with timezone)
            print("Adding session_time column to workout_log...")
            cur.execute("""
                ALTER TABLE workout_log
                ADD COLUMN IF NOT EXISTS session_time TIMESTAMP WITH TIME ZONE;
            """)

            # Set existing records to noon on their session_date
            print("Setting default values for existing records...")
            cur.execute("""
                UPDATE workout_log
                SET session_time = session_date + INTERVAL '12 hours'
                WHERE session_time IS NULL AND session_date IS NOT NULL;
            """)

            conn.commit()
            print("✅ Migration complete!")

if __name__ == "__main__":
    migrate()
