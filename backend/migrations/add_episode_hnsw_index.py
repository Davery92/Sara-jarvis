"""
Migration: Add HNSW index on episode.embedding for fast vector search.

Without this index, vector similarity searches on the episode table do a
sequential scan which degrades as the table grows. HNSW provides approximate
nearest-neighbor search in O(log N) time.

Run with:
    python backend/migrations/add_episode_hnsw_index.py
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
        # Ensure pgvector extension is available
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Check if index already exists
        result = conn.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'episode'
              AND indexname = 'ix_episode_embedding_hnsw'
        """))
        if result.fetchone():
            print("HNSW index already exists, skipping.")
            conn.commit()
            return

        # Create HNSW index for cosine distance on episode embeddings.
        # m=16: connections per node (default, good balance of speed/recall)
        # ef_construction=64: build-time accuracy (default)
        # This index supports the <=> (cosine distance) operator.
        print("Creating HNSW index on episode.embedding (this may take a few minutes)...")
        conn.execute(text("""
            CREATE INDEX ix_episode_embedding_hnsw
            ON episode
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))

        conn.commit()
        print("HNSW index created successfully.")


if __name__ == "__main__":
    run_migration()
