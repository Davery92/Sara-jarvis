"""Add ACS v2 tables: acs_interest_node, acs_interest_edge, acs_self_model, acs_session_log.
Also ALTER acs_session to add cognitive_mode and engagement_score columns."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings


def upgrade():
    engine = create_engine(settings.database_url.replace('+asyncpg', ''))
    with engine.begin() as conn:
        # ── acs_interest_node ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_interest_node')"
        ))
        if result.scalar():
            print("acs_interest_node already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_interest_node (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    label VARCHAR(200) NOT NULL,
                    description TEXT,
                    fascination FLOAT DEFAULT 0.5,
                    depth FLOAT DEFAULT 0.0,
                    confidence FLOAT DEFAULT 0.5,
                    source VARCHAR(50) DEFAULT 'self_discovery',
                    source_detail TEXT,
                    status VARCHAR(30) DEFAULT 'active',
                    times_engaged INTEGER DEFAULT 0,
                    last_engaged_at TIMESTAMPTZ,
                    embedding vector(1024),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, label)
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_interest_node_user ON acs_interest_node (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_interest_node_fascination ON acs_interest_node (user_id, fascination DESC)"))
            conn.execute(text("CREATE INDEX ix_acs_interest_node_status ON acs_interest_node (user_id, status)"))
            # HNSW index for semantic dedup/search
            try:
                conn.execute(text("""
                    CREATE INDEX ix_acs_interest_node_embedding
                    ON acs_interest_node USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                """))
            except Exception as e:
                print(f"HNSW index creation failed (may need pgvector extension): {e}")
            print("Created 'acs_interest_node'.")

        # ── acs_interest_edge ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_interest_edge')"
        ))
        if result.scalar():
            print("acs_interest_edge already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_interest_edge (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    source_node_id VARCHAR NOT NULL REFERENCES acs_interest_node(id) ON DELETE CASCADE,
                    target_node_id VARCHAR NOT NULL REFERENCES acs_interest_node(id) ON DELETE CASCADE,
                    relationship VARCHAR(100) NOT NULL,
                    description TEXT,
                    strength FLOAT DEFAULT 0.5,
                    discovered_during_mode VARCHAR(20),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(source_node_id, target_node_id, relationship)
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_interest_edge_user ON acs_interest_edge (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_interest_edge_source ON acs_interest_edge (source_node_id)"))
            conn.execute(text("CREATE INDEX ix_acs_interest_edge_target ON acs_interest_edge (target_node_id)"))
            print("Created 'acs_interest_edge'.")

        # ── acs_self_model ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_self_model')"
        ))
        if result.scalar():
            print("acs_self_model already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_self_model (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    version INTEGER DEFAULT 1,
                    content JSONB NOT NULL DEFAULT '{}',
                    session_id VARCHAR,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(user_id, version)
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_self_model_user_version ON acs_self_model (user_id, version DESC)"))
            print("Created 'acs_self_model'.")

        # ── acs_session_log ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acs_session_log')"
        ))
        if result.scalar():
            print("acs_session_log already exists, skipping.")
        else:
            conn.execute(text("""
                CREATE TABLE acs_session_log (
                    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id VARCHAR NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
                    session_id VARCHAR,
                    mode VARCHAR(20),
                    engagement_scores JSONB DEFAULT '[]',
                    avg_engagement FLOAT,
                    early_termination BOOLEAN DEFAULT FALSE,
                    turns_completed INTEGER DEFAULT 0,
                    nodes_created INTEGER DEFAULT 0,
                    nodes_updated INTEGER DEFAULT 0,
                    edges_created INTEGER DEFAULT 0,
                    notes_written INTEGER DEFAULT 0,
                    self_model_updated BOOLEAN DEFAULT FALSE,
                    summary TEXT,
                    next_session_intent TEXT,
                    started_at TIMESTAMPTZ DEFAULT NOW(),
                    ended_at TIMESTAMPTZ,
                    duration_minutes FLOAT
                )
            """))
            conn.execute(text("CREATE INDEX ix_acs_session_log_user ON acs_session_log (user_id)"))
            conn.execute(text("CREATE INDEX ix_acs_session_log_session ON acs_session_log (session_id)"))
            conn.execute(text("CREATE INDEX ix_acs_session_log_mode ON acs_session_log (user_id, mode)"))
            print("Created 'acs_session_log'.")

        # ── ALTER acs_session — add cognitive_mode and engagement_score ──
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'acs_session' AND column_name = 'cognitive_mode')"
        ))
        if result.scalar():
            print("acs_session.cognitive_mode already exists, skipping ALTER.")
        else:
            conn.execute(text("ALTER TABLE acs_session ADD COLUMN cognitive_mode VARCHAR(20)"))
            conn.execute(text("ALTER TABLE acs_session ADD COLUMN engagement_score FLOAT"))
            print("Added cognitive_mode and engagement_score to acs_session.")


if __name__ == "__main__":
    upgrade()
