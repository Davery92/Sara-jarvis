"""
Migration: add separate scene-based Temerant RPG tables.

Run with:
    python backend/migrations/add_temerant_rpg_system.py
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
                CREATE TABLE IF NOT EXISTS temerant_rpg_character (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
                    character_name TEXT NOT NULL,
                    origin TEXT NULL,
                    backstory TEXT NULL,
                    body INTEGER NOT NULL DEFAULT 3,
                    mind INTEGER NOT NULL DEFAULT 5,
                    craft INTEGER NOT NULL DEFAULT 3,
                    voice INTEGER NOT NULL DEFAULT 2,
                    luck INTEGER NOT NULL DEFAULT 3,
                    coin_talents DOUBLE PRECISION NOT NULL DEFAULT 38.0,
                    rank VARCHAR(32) NOT NULL DEFAULT 'none',
                    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
                    skills JSONB NOT NULL DEFAULT '{}'::jsonb,
                    inventory JSONB NOT NULL DEFAULT '[]'::jsonb,
                    term_index INTEGER NOT NULL DEFAULT 1,
                    current_scene_id VARCHAR NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_world_state (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_rpg_character(id) ON DELETE CASCADE,
                    local_date DATE NOT NULL,
                    day_slot VARCHAR(16) NOT NULL DEFAULT 'afternoon',
                    weather VARCHAR(64) NOT NULL DEFAULT 'autumn chill',
                    location_hint VARCHAR(128) NOT NULL DEFAULT 'Imre',
                    ambient_events JSONB NOT NULL DEFAULT '[]'::jsonb,
                    pending_consequences JSONB NOT NULL DEFAULT '[]'::jsonb,
                    last_advance_summary TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_scene (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_rpg_character(id) ON DELETE CASCADE,
                    scene_number INTEGER NOT NULL,
                    local_date DATE NOT NULL,
                    day_slot VARCHAR(16) NOT NULL,
                    location VARCHAR(128) NOT NULL,
                    title VARCHAR(180) NOT NULL,
                    opening_text TEXT NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    summary TEXT NULL,
                    consequences JSONB NOT NULL DEFAULT '[]'::jsonb,
                    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    closed_at TIMESTAMPTZ NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_temerant_rpg_scene_user_opened
                ON temerant_rpg_scene (user_id, opened_at)
                """
            )
        )

        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_temerant_rpg_character_scene'
                    ) THEN
                        ALTER TABLE temerant_rpg_character
                        ADD CONSTRAINT fk_temerant_rpg_character_scene
                        FOREIGN KEY (current_scene_id) REFERENCES temerant_rpg_scene(id) ON DELETE SET NULL;
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_scene_turn (
                    id VARCHAR PRIMARY KEY,
                    scene_id VARCHAR NOT NULL REFERENCES temerant_rpg_scene(id) ON DELETE CASCADE,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    turn_index INTEGER NOT NULL,
                    player_action TEXT NOT NULL,
                    gm_response TEXT NOT NULL,
                    resolution JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_temerant_rpg_scene_turn_scene_idx
                ON temerant_rpg_scene_turn (scene_id, turn_index)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_relationship (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_rpg_character(id) ON DELETE CASCADE,
                    npc_key VARCHAR(64) NOT NULL,
                    display_name VARCHAR(128) NOT NULL,
                    disposition VARCHAR(24) NOT NULL DEFAULT 'neutral',
                    trust VARCHAR(24) NOT NULL DEFAULT 'guarded',
                    respect VARCHAR(24) NOT NULL DEFAULT 'neutral',
                    debt_balance INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_rpg_relationship_character_npc UNIQUE (character_id, npc_key)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_journal_entry (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_rpg_character(id) ON DELETE CASCADE,
                    local_date DATE NOT NULL,
                    summary_markdown TEXT NOT NULL,
                    scene_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_rpg_journal_user_date UNIQUE (user_id, local_date)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS temerant_rpg_term (
                    id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    character_id VARCHAR NOT NULL REFERENCES temerant_rpg_character(id) ON DELETE CASCADE,
                    term_index INTEGER NOT NULL,
                    month DATE NOT NULL,
                    admissions_result VARCHAR(24) NOT NULL DEFAULT 'mixed',
                    tuition_talents DOUBLE PRECISION NOT NULL DEFAULT 10.0,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_temerant_rpg_term_user_index UNIQUE (user_id, term_index)
                )
                """
            )
        )

        conn.commit()
        print("[DONE] temerant_rpg system migration complete")


if __name__ == "__main__":
    run_migration()
