"""Extend the existing recipe table with knowledge-garden fields.

The base `recipe` table is created by add_recovery_recipes_workout_enhancements.py
(used by routes/fitness.py). This migration adds the columns needed for Sara's
chat-driven recipe tools: tags, embedding, starred, last_made_at, times_made,
meal_type, cuisine, source_url, source_name, recipe_notes, rating,
cook_time_minutes. Idempotent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import settings  # noqa: E402


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).scalar() is not None


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    if _column_exists(conn, table, column):
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    print(f"  + added {table}.{column}")


def upgrade() -> None:
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    dim = settings.embedding_dim

    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables WHERE table_name = 'recipe'
        """)).scalar()
        if not exists:
            print("recipe table missing — run add_recovery_recipes_workout_enhancements.py first.")
            return

        # Knowledge-garden columns
        _add_column(conn, "recipe", "cook_time_minutes", "INTEGER")
        _add_column(conn, "recipe", "meal_type", "TEXT")
        _add_column(conn, "recipe", "cuisine", "TEXT")
        _add_column(conn, "recipe", "tags", "JSONB NOT NULL DEFAULT '[]'::jsonb")
        _add_column(conn, "recipe", "source_url", "TEXT")
        _add_column(conn, "recipe", "source_name", "TEXT")
        _add_column(conn, "recipe", "recipe_notes", "TEXT DEFAULT ''")
        _add_column(conn, "recipe", "starred", "BOOLEAN NOT NULL DEFAULT FALSE")
        _add_column(conn, "recipe", "rating", "INTEGER")
        _add_column(conn, "recipe", "last_made_at", "TIMESTAMPTZ")
        _add_column(conn, "recipe", "times_made", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "recipe", "embedding", f"vector({dim})")

        # Indexes (idempotent)
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_recipe_updated_at ON recipe(updated_at DESC)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_recipe_starred ON recipe(user_id, starred) WHERE starred"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_recipe_meal_type ON recipe(user_id, meal_type)"))
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_recipe_embedding_hnsw "
                "ON recipe USING hnsw (embedding vector_cosine_ops)"
            ))
        except Exception as e:
            print(f"  HNSW index skipped: {e}")
        print("Recipe knowledge-garden columns & indexes ensured.")


if __name__ == "__main__":
    upgrade()
