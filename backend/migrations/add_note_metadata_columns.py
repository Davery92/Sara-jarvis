"""
Migration: add persisted tags and starred metadata to notes.

Run: python backend/migrations/add_note_metadata_columns.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://sara:sara123@10.185.1.180:5432/sara_hub",
)


def run_migration():
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)

    if "note" not in inspector.get_table_names():
        print("ℹ️ note table does not exist yet")
        return

    existing_columns = {column["name"] for column in inspector.get_columns("note")}
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if "starred" not in existing_columns:
            starred_default = "0" if dialect == "sqlite" else "FALSE"
            conn.execute(
                text(f"ALTER TABLE note ADD COLUMN starred BOOLEAN DEFAULT {starred_default} NOT NULL")
            )

        if "tags" not in existing_columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE note ADD COLUMN tags JSON DEFAULT '[]' NOT NULL"))
            else:
                conn.execute(text("ALTER TABLE note ADD COLUMN tags JSON DEFAULT '[]'::json NOT NULL"))

    print("✅ note metadata columns are ready")


if __name__ == "__main__":
    run_migration()
