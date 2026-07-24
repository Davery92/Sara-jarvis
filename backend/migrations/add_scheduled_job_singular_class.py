"""
Migration: add `singular_class` column to `scheduled_job` (SINGULAR_SARA_
MASTER_PLAN §C11 scheduler diet).

Additive, nullable — classifies each job into sensor | maintenance | anchor
| legacy_cognition | unclassified per the same heuristic already used by
`scripts/singular_sara_inventory.py`, so the eventual scheduler diet has a
persisted starting point instead of re-running a script each time. Backfill
via `app.services.scheduler_diet.backfill_singular_class` after this runs.

Run:
  docker compose -f docker-compose.dev.yml exec -T backend \\
    python migrations/add_scheduled_job_singular_class.py
"""

import os

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub",
)


def run_migration():
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE scheduled_job
            ADD COLUMN IF NOT EXISTS singular_class VARCHAR(30)
        """))
        print("  Added column: scheduled_job.singular_class")

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_scheduled_job_singular_class
            ON scheduled_job (singular_class)
        """))
        print("  Created index")

    print("\nMigration complete: scheduled_job.singular_class")


if __name__ == "__main__":
    print("Running migration: add_scheduled_job_singular_class")
    print(f"Database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    print()
    try:
        run_migration()
        print("\nMigration completed successfully!")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        raise
