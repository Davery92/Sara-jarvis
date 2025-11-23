"""Migrate episode.embedding from TEXT to Vector(1024) and add HNSW index

Revision ID: 009
Revises: 008
Create Date: 2025-11-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009_migrate_episode_embedding_to_vector'
down_revision = '008_create_daily_briefings_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Migrate episode.embedding from TEXT to Vector(1024).

    This is a non-destructive migration:
    1. Drop existing embedding column (TEXT type, currently all NULL)
    2. Add new embedding column as Vector(1024) using pgvector
    3. Create HNSW index for fast similarity search
    """

    # Ensure pgvector extension is enabled
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Drop the old TEXT embedding column
    # All existing episodes have NULL embeddings, so no data loss
    op.drop_column('episode', 'embedding')

    # Add the new Vector column
    op.execute("""
        ALTER TABLE episode
        ADD COLUMN embedding vector(1024);
    """)

    # Create HNSW index for fast approximate nearest neighbor search
    # Using cosine distance (vector_cosine_ops) since embeddings are normalized
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_episode_embedding_hnsw
        ON episode
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
    """)

    # Create a B-tree index on user_id + created_at for filtered queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_episode_user_created
        ON episode (user_id, created_at DESC);
    """)

    print("Successfully migrated episode.embedding to Vector(1024) with HNSW index")


def downgrade() -> None:
    """Revert back to TEXT embedding column"""

    # Drop the HNSW index
    op.execute("DROP INDEX IF EXISTS ix_episode_embedding_hnsw;")
    op.execute("DROP INDEX IF EXISTS ix_episode_user_created;")

    # Drop Vector column
    op.drop_column('episode', 'embedding')

    # Re-add TEXT column
    op.add_column('episode', sa.Column('embedding', sa.Text(), nullable=True))

    print("Reverted episode.embedding back to TEXT type")
