"""Add acs_session.premature_done_count column for PR 1.

One-column migration. No backfill: default 0 is correct for historical rows
since the suppression rule did not exist before this PR. Idempotent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402


def upgrade() -> None:
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.begin() as conn:
        col_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'acs_session' AND column_name = 'premature_done_count'
        """)).scalar()
        if col_exists:
            print("acs_session.premature_done_count already exists, skipping.")
            return
        conn.execute(text(
            "ALTER TABLE acs_session "
            "ADD COLUMN premature_done_count INTEGER NOT NULL DEFAULT 0"
        ))
        print("Added acs_session.premature_done_count column (default 0).")


if __name__ == "__main__":
    upgrade()
