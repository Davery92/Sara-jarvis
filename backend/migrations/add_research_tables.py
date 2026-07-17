"""Add research_plan and research_message tables for the research delegation system."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from app.db.session import get_db


def run_migration():
    db = next(get_db())
    try:
        # Research Plan table
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS research_plan (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                title VARCHAR NOT NULL,
                objective TEXT NOT NULL,
                steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                status VARCHAR NOT NULL DEFAULT 'draft',
                created_by VARCHAR NOT NULL DEFAULT 'sara',
                current_step_index INTEGER DEFAULT 0,
                findings_summary TEXT,
                model_id VARCHAR DEFAULT 'Qwen3.5-27B',
                container_vmid INTEGER,
                total_tokens_used INTEGER DEFAULT 0,
                error_log TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            )
        """))

        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_research_plan_user_id ON research_plan(user_id)
        """))

        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_research_plan_status ON research_plan(status)
        """))

        # Research Message table
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS research_message (
                id VARCHAR PRIMARY KEY,
                plan_id VARCHAR NOT NULL REFERENCES research_plan(id) ON DELETE CASCADE,
                direction VARCHAR NOT NULL,
                content TEXT NOT NULL,
                step_index INTEGER,
                status VARCHAR NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                answered_at TIMESTAMP
            )
        """))

        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_research_message_plan_id ON research_message(plan_id)
        """))

        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_research_message_status ON research_message(status)
        """))

        db.commit()
        print("Migration complete: research_plan and research_message tables created.")

    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
