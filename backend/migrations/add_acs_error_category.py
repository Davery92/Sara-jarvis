"""Add acs_session.error_category column for structured failure taxonomy.

Adds a nullable VARCHAR(32) column with an index, then backfills it from
existing error_log values using the same regex classifier the live code
uses (app.services.acs.error_taxonomy.classify_from_text).

Idempotent: safe to re-run.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.acs.error_taxonomy import (  # noqa: E402
    classify_from_text,
    _REAPER_END_REASONS,
    _BENIGN_END_REASONS,
)


def upgrade() -> None:
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.begin() as conn:
        col_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'acs_session' AND column_name = 'error_category'
        """)).scalar()
        if not col_exists:
            conn.execute(text(
                "ALTER TABLE acs_session ADD COLUMN error_category VARCHAR(32) NULL"
            ))
            conn.execute(text(
                "CREATE INDEX ix_acs_session_error_category ON acs_session (error_category)"
            ))
            print("Added acs_session.error_category column + index.")
        else:
            print("acs_session.error_category already exists, skipping column add.")

        # Backfill: reaper end_reasons mirror, error rows go through text classifier.
        # Skip rows that already have a category set so re-runs don't churn.
        rows = conn.execute(text("""
            SELECT id, end_reason, error_log
            FROM acs_session
            WHERE error_category IS NULL
              AND end_reason IS NOT NULL
        """)).fetchall()

        updated = 0
        skipped_benign = 0
        by_category: dict[str, int] = {}

        for row_id, end_reason, error_log in rows:
            category = _resolve_backfill_category(end_reason, error_log)
            if category is None:
                skipped_benign += 1
                continue
            conn.execute(
                text("UPDATE acs_session SET error_category = :c WHERE id = :sid"),
                {"c": category, "sid": row_id},
            )
            by_category[category] = by_category.get(category, 0) + 1
            updated += 1

        print(f"Backfilled {updated} rows; left {skipped_benign} benign rows NULL.")
        for cat, n in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {cat:32s} {n}")


def _resolve_backfill_category(end_reason: str, error_log: str | None) -> str | None:
    """Backfill rule mirror of classify_termination, applied to historical rows."""
    if end_reason in _BENIGN_END_REASONS:
        return None
    if end_reason in _REAPER_END_REASONS:
        return end_reason
    # end_reason == 'error' or anything not in the above buckets
    cat = classify_from_text(error_log)
    if cat is not None:
        return cat
    if end_reason == "error":
        from app.services.acs.error_taxonomy import UNKNOWN
        return UNKNOWN
    return None


if __name__ == "__main__":
    upgrade()
