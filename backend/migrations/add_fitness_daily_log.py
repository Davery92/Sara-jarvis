#!/usr/bin/env python3
"""
Migration: Add fitness_daily_log table for daily fitness activity summaries
"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
)

engine = create_engine(DATABASE_URL)

def migrate():
    with engine.begin() as conn:
        # Create fitness_daily_log table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fitness_daily_log (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                log_date DATE NOT NULL,

                -- Activity counts
                chat_count INTEGER DEFAULT 0,
                food_entries INTEGER DEFAULT 0,
                workout_sessions INTEGER DEFAULT 0,
                notes_created INTEGER DEFAULT 0,

                -- Nutrition summary
                total_calories FLOAT,
                total_protein FLOAT,
                total_carbs FLOAT,
                total_fats FLOAT,

                -- Workout summary
                total_exercises INTEGER DEFAULT 0,
                total_sets INTEGER DEFAULT 0,
                total_reps INTEGER DEFAULT 0,

                -- Summary text
                summary TEXT,

                -- Timestamps
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(user_id, log_date)
            );
        """))

        # Create indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_fitness_daily_log_user_date
            ON fitness_daily_log(user_id, log_date DESC);
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_fitness_daily_log_date
            ON fitness_daily_log(log_date DESC);
        """))

        print("✅ fitness_daily_log table created successfully")

if __name__ == "__main__":
    migrate()
    print("Migration complete!")
