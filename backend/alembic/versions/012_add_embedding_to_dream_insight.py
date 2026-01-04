"""add embedding to dream insight

Revision ID: 012_insight_embedding
Revises: 011_insight_mention
Create Date: 2025-11-25 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False

# revision identifiers, used by Alembic.
revision = '012_insight_embedding'
down_revision = '011_insight_mention'
branch_labels = None
depends_on = None


def upgrade():
    # Add embedding column to dream_insight table
    if PGVECTOR_AVAILABLE:
        op.add_column('dream_insight', sa.Column('embedding', Vector(1024), nullable=True))
    else:
        op.add_column('dream_insight', sa.Column('embedding', sa.Text(), nullable=True))

    # Create index for vector similarity search
    op.execute('CREATE INDEX IF NOT EXISTS idx_dream_insight_embedding ON dream_insight USING hnsw (embedding vector_l2_ops)')


def downgrade():
    op.drop_index('idx_dream_insight_embedding', table_name='dream_insight')
    op.drop_column('dream_insight', 'embedding')
