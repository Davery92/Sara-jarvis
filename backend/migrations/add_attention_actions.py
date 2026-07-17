"""
Migration: Add action columns to autonomy_attention_item.

Adds:
  - completed_at TIMESTAMPTZ — when an item was marked completed
  - action_history JSONB DEFAULT '[]' — log of actions taken on the item

Run with:
    python backend/migrations/add_attention_actions.py
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sara:sara123@10.185.1.180:5432/sara_hub"
    )
    return create_engine(database_url)


def run_migration():
    engine = get_engine()

    with engine.connect() as conn:
        # Add completed_at column
        conn.execute(text("""
            ALTER TABLE autonomy_attention_item
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ
        """))
        print("Added completed_at column")

        # Add action_history column
        conn.execute(text("""
            ALTER TABLE autonomy_attention_item
            ADD COLUMN IF NOT EXISTS action_history JSONB DEFAULT '[]'::jsonb
        """))
        print("Added action_history column")

        conn.commit()
        print("Migration complete: add_attention_actions")


if __name__ == "__main__":
    run_migration()
