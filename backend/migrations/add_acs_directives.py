"""Add acs_directive table — David-to-ACS communication channel."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_directive')"
        ))
        if result.scalar():
            print("acs_directive already exists, skipping.")
            return

        conn.execute(text("""
            CREATE TABLE acs_directive (
                id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                directive_type VARCHAR NOT NULL,
                content TEXT NOT NULL,
                priority VARCHAR NOT NULL DEFAULT 'normal',
                status VARCHAR NOT NULL DEFAULT 'pending',
                source VARCHAR NOT NULL DEFAULT 'api',
                response TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                acknowledged_at TIMESTAMPTZ,
                expired_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("CREATE INDEX ix_acs_directive_user ON acs_directive (user_id)"))
        conn.execute(text("CREATE INDEX ix_acs_directive_status ON acs_directive (status)"))
        conn.execute(text("CREATE INDEX ix_acs_directive_user_status ON acs_directive (user_id, status)"))
        print("Created 'acs_directive'.")


if __name__ == "__main__":
    upgrade()
