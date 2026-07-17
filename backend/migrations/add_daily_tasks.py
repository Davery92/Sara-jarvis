"""Create daily_task table for per-day task management."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        # Check if table exists
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_task')"
        ))
        if result.scalar():
            print("Table 'daily_task' already exists, skipping.")
            return

        conn.execute(text("""
            CREATE TABLE daily_task (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                title VARCHAR NOT NULL,
                description TEXT,
                task_date DATE NOT NULL DEFAULT CURRENT_DATE,
                priority VARCHAR DEFAULT 'normal',
                is_completed BOOLEAN DEFAULT FALSE,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(text(
            "CREATE INDEX ix_daily_task_user_date ON daily_task (user_id, task_date)"
        ))

        print("Created 'daily_task' table with index on (user_id, task_date).")


if __name__ == "__main__":
    upgrade()
