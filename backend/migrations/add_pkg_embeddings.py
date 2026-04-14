"""
Migration: Add pkg_embedding table for PKG vector search via pgvector.

Stores embeddings of PKG node content for semantic similarity search,
complementing the text-based CONTAINS matching in Neo4j.

Run with:
    python backend/migrations/add_pkg_embeddings.py
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
        # Ensure pgvector extension
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Check if table exists
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'pkg_embedding'
        """))
        if result.fetchone():
            print("pkg_embedding table already exists, checking for HNSW index...")
        else:
            # Create table
            conn.execute(text("""
                CREATE TABLE pkg_embedding (
                    pkg_id VARCHAR PRIMARY KEY,
                    node_type VARCHAR NOT NULL,
                    content_text TEXT NOT NULL,
                    embedding vector(1024),
                    confidence FLOAT DEFAULT 0.7,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            print("Created pkg_embedding table.")

            # Index on node_type
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_pkg_embedding_node_type
                ON pkg_embedding (node_type)
            """))

        # HNSW index for cosine similarity search
        result = conn.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'pkg_embedding'
              AND indexname = 'ix_pkg_embedding_hnsw'
        """))
        if result.fetchone():
            print("HNSW index already exists, skipping.")
        else:
            print("Creating HNSW index on pkg_embedding.embedding...")
            conn.execute(text("""
                CREATE INDEX ix_pkg_embedding_hnsw
                ON pkg_embedding
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))
            print("HNSW index created.")

        conn.commit()
        print("Migration complete.")


if __name__ == "__main__":
    run_migration()
