"""
Migration: Add Temerant RPG system tables.

Creates:
  - temerant_character
  - temerant_attribute_state
  - temerant_xp_ledger
  - temerant_daily_state
  - temerant_story_thread
  - temerant_oracle_event
  - temerant_term
  - temerant_masterwork
  - temerant_mapping_rule
  - temerant_journal_entry
  - temerant_ingestion_cursor

Run with:
    python backend/migrations/add_temerant_system.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text


def get_engine():
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://sara:sara123@10.185.1.180:5432/sara_hub",
    )
    return create_engine(database_url)


def run_migration():
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_character (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
                    character_name TEXT NOT NULL,
                    backstory TEXT NULL,
                    origin TEXT NULL,
                    current_rank VARCHAR(32) NOT NULL DEFAULT 'elir',
                    coin_balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    alar_strength INTEGER NOT NULL DEFAULT 0,
                    naming_affinity INTEGER NOT NULL DEFAULT 0,
                    specialization_track VARCHAR(32) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT chk_temerant_character_rank
                        CHECK (current_rank IN ('elir', 'relar', 'elthe'))
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_story_thread (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'open',
                    last_event_at TIMESTAMPTZ NULL,
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_oracle_event (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    thread_id VARCHAR NULL REFERENCES temerant_story_thread(id) ON DELETE SET NULL,
                    local_date DATE NOT NULL,
                    tier VARCHAR(16) NOT NULL,
                    category VARCHAR(32) NOT NULL,
                    title TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    stakes TEXT NULL,
                    options JSONB NULL,
                    resolution TEXT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved_at TIMESTAMPTZ NULL
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_attribute_state (
                    id VARCHAR PRIMARY KEY,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    attribute VARCHAR(32) NOT NULL,
                    xp_total INTEGER NOT NULL DEFAULT 0,
                    xp_term INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_attribute_state_character_attr
                        UNIQUE (character_id, attribute)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_xp_ledger (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    source_type VARCHAR(64) NOT NULL,
                    source_ref_id VARCHAR(255) NULL,
                    idempotency_key VARCHAR(255) NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    local_date DATE NOT NULL,
                    attribute VARCHAR(32) NOT NULL,
                    subdomain VARCHAR(64) NULL,
                    xp_delta INTEGER NOT NULL DEFAULT 0,
                    coin_delta DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    name_delta INTEGER NOT NULL DEFAULT 0,
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_ledger_idempotency UNIQUE (idempotency_key)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_temerant_ledger_user_date "
                "ON temerant_xp_ledger (user_id, local_date)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_temerant_ledger_character_attr_time "
                "ON temerant_xp_ledger (character_id, attribute, occurred_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_temerant_ledger_source "
                "ON temerant_xp_ledger (source_type, source_ref_id)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_daily_state (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    local_date DATE NOT NULL,
                    categories_completed INTEGER NOT NULL DEFAULT 0,
                    body_xp INTEGER NOT NULL DEFAULT 0,
                    mind_xp INTEGER NOT NULL DEFAULT 0,
                    craft_xp INTEGER NOT NULL DEFAULT 0,
                    coin_xp INTEGER NOT NULL DEFAULT 0,
                    name_xp INTEGER NOT NULL DEFAULT 0,
                    oracle_roll_raw INTEGER NULL,
                    oracle_roll_modified INTEGER NULL,
                    oracle_event_id VARCHAR NULL REFERENCES temerant_oracle_event(id) ON DELETE SET NULL,
                    term_month DATE NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_daily_state_user_date UNIQUE (user_id, local_date)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_term (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    term_month DATE NOT NULL,
                    completion_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    admissions_result VARCHAR(16) NOT NULL DEFAULT 'good',
                    tuition_talents INTEGER NOT NULL DEFAULT 10,
                    xp_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    coin_delta DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    review_markdown TEXT NULL,
                    locked_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_term_user_month UNIQUE (user_id, term_month)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_masterwork (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'planned',
                    evidence JSONB NULL,
                    completed_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_mapping_rule (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    source_kind VARCHAR(64) NOT NULL,
                    source_ref VARCHAR(255) NULL,
                    target_attribute VARCHAR(32) NOT NULL,
                    target_subdomain VARCHAR(64) NULL,
                    xp_base INTEGER NOT NULL DEFAULT 1,
                    bonus_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
                    daily_cap INTEGER NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_journal_entry (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_character(id) ON DELETE CASCADE,
                    local_date DATE NOT NULL,
                    summary_structured JSONB NOT NULL DEFAULT '{}'::jsonb,
                    summary_markdown TEXT NOT NULL,
                    source_event_count INTEGER NOT NULL DEFAULT 0,
                    generated_by VARCHAR(32) NOT NULL DEFAULT 'rules',
                    model VARCHAR(128) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_journal_user_date UNIQUE (user_id, local_date)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_ingestion_cursor (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    source_type VARCHAR(64) NOT NULL,
                    cursor_value VARCHAR(255) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_ingestion_cursor_user_source
                        UNIQUE (user_id, source_type)
                )
                """
            )
        )

        conn.commit()
        print("[DONE] temerant system migration complete")


if __name__ == "__main__":
    run_migration()
