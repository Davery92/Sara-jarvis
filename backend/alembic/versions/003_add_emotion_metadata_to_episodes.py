"""add emotion_metadata to episodes

Revision ID: 003_emotion_metadata
Revises: 002_lifeos_context
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '003_emotion_metadata'
down_revision = '002_lifeos_context'
branch_labels = None
depends_on = None


def upgrade():
    # Add emotion_metadata column to episode table
    op.add_column('episode', sa.Column('emotion_metadata', JSON, nullable=True))

    # Create index for emotion queries
    op.execute("""
        CREATE INDEX ix_episode_emotion_sentiment
        ON episode ((emotion_metadata->>'sentiment'))
        WHERE emotion_metadata IS NOT NULL
    """)

    # Create index for emotion type
    op.execute("""
        CREATE INDEX ix_episode_emotion_type
        ON episode ((emotion_metadata->>'primary_emotion'))
        WHERE emotion_metadata IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_episode_emotion_sentiment")
    op.execute("DROP INDEX IF EXISTS ix_episode_emotion_type")
    op.drop_column('episode', 'emotion_metadata')
