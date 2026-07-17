"""Add ACS (Autonomous Cognition System) tables: acs_session, acs_curiosity_queue, acs_show_david_buffer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        # ── acs_session ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_session')"
        ))
        if result.scalar():
            print("acs_session already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_session (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    vm_session_id VARCHAR,
                    model_id VARCHAR NOT NULL DEFAULT 'Qwen3.5-122B-A10B',
                    state VARCHAR NOT NULL DEFAULT 'autonomous',
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    paused_at TIMESTAMPTZ,
                    ended_at TIMESTAMPTZ,
                    end_reason VARCHAR,
                    turns_completed INTEGER DEFAULT 0,
                    notes_created INTEGER DEFAULT 0,
                    curiosities_explored INTEGER DEFAULT 0,
                    token_usage JSONB DEFAULT '{}',
                    context_summary TEXT,
                    error_log TEXT
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_session_user ON acs_session (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_session_state ON acs_session (state)"))
            conn.execute(text("CREATE INDEX ix_acs_session_started ON acs_session (started_at DESC)"))
            print("Created 'acs_session'.")

        # ── acs_curiosity_queue ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_curiosity_queue')"
        ))
        if result.scalar():
            print("acs_curiosity_queue already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_curiosity_queue (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    topic TEXT NOT NULL,
                    source VARCHAR NOT NULL DEFAULT 'self',
                    priority FLOAT DEFAULT 0.5,
                    status VARCHAR NOT NULL DEFAULT 'queued',
                    exploration_notes TEXT,
                    related_note_ids JSONB DEFAULT '[]',
                    session_id VARCHAR,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_curiosity_user ON acs_curiosity_queue (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_curiosity_status ON acs_curiosity_queue (status)"))
            conn.execute(text("CREATE INDEX ix_acs_curiosity_session ON acs_curiosity_queue (session_id)"))
            print("Created 'acs_curiosity_queue'.")

        # ── acs_show_david_buffer ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_show_david_buffer')"
        ))
        if result.scalar():
            print("acs_show_david_buffer already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_show_david_buffer (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    title VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    category VARCHAR NOT NULL DEFAULT 'discovery',
                    priority FLOAT DEFAULT 0.5,
                    shown BOOLEAN DEFAULT FALSE,
                    shown_at TIMESTAMPTZ,
                    session_id VARCHAR,
                    related_note_id VARCHAR,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_show_david_user ON acs_show_david_buffer (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_show_david_shown ON acs_show_david_buffer (shown)"))
            conn.execute(text("CREATE INDEX ix_acs_show_david_session ON acs_show_david_buffer (session_id)"))
            print("Created 'acs_show_david_buffer'.")


if __name__ == "__main__":
    upgrade()
