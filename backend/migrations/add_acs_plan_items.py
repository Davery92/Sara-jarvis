"""Add acs_plan_item table — daily work items for ACS autonomous planning."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_plan_item')"
        ))
        if result.scalar():
            print("acs_plan_item already exists, skipping.")
            return

        conn.execute(text("""
            CREATE TABLE acs_plan_item (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                plan_date DATE NOT NULL,
                title VARCHAR NOT NULL,
                description TEXT NOT NULL,
                success_criteria TEXT,
                priority INTEGER NOT NULL DEFAULT 50,
                status VARCHAR NOT NULL DEFAULT 'pending',
                source VARCHAR NOT NULL DEFAULT 'morning_plan',
                source_ref VARCHAR,
                estimated_turns INTEGER,
                assigned_session_id VARCHAR,
                result_summary TEXT,
                blocker_reason TEXT,
                depends_on VARCHAR,
                cognitive_mode VARCHAR NOT NULL DEFAULT 'execution',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX ix_acs_plan_item_user ON acs_plan_item (user_id)"))
        conn.execute(text("CREATE INDEX ix_acs_plan_item_plan_date ON acs_plan_item (plan_date)"))
        conn.execute(text("CREATE INDEX ix_acs_plan_item_user_date_status ON acs_plan_item (user_id, plan_date, status)"))
        print("Created 'acs_plan_item'.")


if __name__ == "__main__":
    upgrade()
