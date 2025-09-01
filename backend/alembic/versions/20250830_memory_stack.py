"""
Add human-like memory stack tables

Revision ID: 20250830_memory_stack
Revises: 3fe9de76a45e
Create Date: 2025-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = '20250830_memory_stack'
down_revision = '3fe9de76a45e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector when on Postgres
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create tables if not present (portable and idempotent)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_trace (
          id VARCHAR(36) PRIMARY KEY,
          user_id VARCHAR(36) NOT NULL,
          content TEXT NOT NULL,
          role VARCHAR(32),
          created_at TIMESTAMPTZ DEFAULT now(),
          salience DOUBLE PRECISION,
          source TEXT,
          meta TEXT
        );
        """
    )

    # Use vector(1024) for embedding column name 'embedding' to match runtime models
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_embedding (
          trace_id VARCHAR(36) NOT NULL,
          head VARCHAR(32) NOT NULL,
          embedding VECTOR(1024),
          created_at TIMESTAMPTZ DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_embedding_trace ON memory_embedding (trace_id, head);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_edge (
          src VARCHAR(36) NOT NULL,
          dst VARCHAR(36) NOT NULL,
          type VARCHAR(64) NOT NULL,
          weight DOUBLE PRECISION,
          ts TIMESTAMPTZ DEFAULT now(),
          PRIMARY KEY (src, dst, type)
        );
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_trace_created_at ON memory_trace (created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_trace_salience ON memory_trace (salience);")
    # HNSW index on embedding (skip if unsupported)
    # Try HNSW with explicit operator class, fallback to IVFFLAT
    try:
        op.execute("CREATE INDEX IF NOT EXISTS ix_mem_embedding_hnsw ON memory_embedding USING hnsw (embedding vector_l2_ops);")
    except Exception:
        try:
            op.execute("CREATE INDEX IF NOT EXISTS ix_mem_embedding_ivfflat ON memory_embedding USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
        except Exception:
            pass


def downgrade() -> None:
    # Non-destructive downgrade: drop indexes and tables if needed
    try:
        op.execute('DROP INDEX IF EXISTS ix_mem_embedding_hnsw;')
    except Exception:
        pass
    op.execute('DROP INDEX IF EXISTS ix_memory_embedding_trace;')
    op.execute('DROP INDEX IF EXISTS ix_memory_trace_salience;')
    op.execute('DROP INDEX IF EXISTS ix_memory_trace_created_at;')
    op.execute('DROP TABLE IF EXISTS memory_edge;')
    op.execute('DROP TABLE IF EXISTS memory_embedding;')
    op.execute('DROP TABLE IF EXISTS memory_trace;')
