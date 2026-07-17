"""Add ACS autonomy-control columns and durable transcript storage."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text

from app.core.config import settings


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table_name AND column_name = :column_name)"
    ), {"table_name": table_name, "column_name": column_name})
    return bool(result.scalar())


def _add_column_if_missing(conn, table_name: str, column_name: str, ddl: str):
    if _column_exists(conn, table_name, column_name):
        print(f"{table_name}.{column_name} already exists, skipping.")
        return
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
    print(f"Added {table_name}.{column_name}")


def upgrade():
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.begin() as conn:
        _add_column_if_missing(conn, "acs_plan_item", "reopen_after", "reopen_after TIMESTAMPTZ")
        _add_column_if_missing(conn, "acs_plan_item", "revisit_count", "revisit_count INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "acs_plan_item", "last_meaningful_progress_at", "last_meaningful_progress_at TIMESTAMPTZ")
        _add_column_if_missing(conn, "acs_plan_item", "closure_reason", "closure_reason VARCHAR")
        _add_column_if_missing(conn, "acs_plan_item", "parked_at", "parked_at TIMESTAMPTZ")

        _add_column_if_missing(conn, "acs_interest_node", "revisit_count", "revisit_count INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "acs_interest_node", "cooldown_until", "cooldown_until TIMESTAMPTZ")

        _add_column_if_missing(conn, "acs_show_david_buffer", "dedupe_key", "dedupe_key VARCHAR")
        _add_column_if_missing(conn, "acs_show_david_buffer", "delivery_status", "delivery_status VARCHAR NOT NULL DEFAULT 'queued'")
        _add_column_if_missing(conn, "acs_show_david_buffer", "suppression_reason", "suppression_reason TEXT")
        _add_column_if_missing(conn, "acs_show_david_buffer", "merged_into_id", "merged_into_id VARCHAR")
        _add_column_if_missing(conn, "acs_show_david_buffer", "shared_reason", "shared_reason VARCHAR NOT NULL DEFAULT 'interesting_discovery'")
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_acs_show_david_dedupe_key ON acs_show_david_buffer (user_id, dedupe_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_acs_show_david_delivery_status ON acs_show_david_buffer (user_id, delivery_status)"))

        _add_column_if_missing(conn, "acs_session_log", "primary_topic", "primary_topic VARCHAR(200)")
        _add_column_if_missing(conn, "acs_session_log", "primary_objective", "primary_objective TEXT")
        _add_column_if_missing(conn, "acs_session_log", "expected_artifact", "expected_artifact TEXT")
        _add_column_if_missing(conn, "acs_session_log", "outcome_type", "outcome_type VARCHAR(50)")
        _add_column_if_missing(conn, "acs_session_log", "artifact_summary", "artifact_summary TEXT")
        _add_column_if_missing(conn, "acs_session_log", "outbound_messages", "outbound_messages INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "acs_session_log", "suppressed_messages", "suppressed_messages INTEGER NOT NULL DEFAULT 0")

        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_session_transcript')"
        ))
        if result.scalar():
            print("acs_session_transcript already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_session_transcript (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    session_id VARCHAR NOT NULL UNIQUE REFERENCES acs_session(id) ON DELETE CASCADE,
                    mode VARCHAR(20),
                    started_at TIMESTAMPTZ,
                    transcript_json JSONB NOT NULL DEFAULT '{}',
                    raw_text TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_session_transcript_user ON acs_session_transcript (user_id, created_at DESC)"))
            print("Created 'acs_session_transcript'.")


if __name__ == "__main__":
    upgrade()
