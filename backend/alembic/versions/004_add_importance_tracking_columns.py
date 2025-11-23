"""add importance tracking columns

Revision ID: 004_importance_tracking
Revises: 003_emotion_metadata
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '004_importance_tracking'
down_revision = '003_emotion_metadata'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns to episode table (skip access_count and last_accessed as they already exist)
    op.add_column('episode', sa.Column('base_importance', sa.Float(), nullable=True))
    op.add_column('episode', sa.Column('importance_last_updated', sa.DateTime(timezone=True), nullable=True))
    # access_count and last_accessed already exist in the schema
    op.add_column('episode', sa.Column('user_rating', sa.Float(), nullable=True))
    op.add_column('episode', sa.Column('consolidated', sa.Boolean(), nullable=True, server_default='false'))

    # Backfill base_importance from current importance
    op.execute("""
        UPDATE episode
        SET base_importance = importance
        WHERE base_importance IS NULL AND importance IS NOT NULL
    """)

    # Create memory_references table for cross-reference tracking
    op.create_table(
        'memory_references',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_episode_id', sa.String(), nullable=False),
        sa.Column('target_episode_id', sa.String(), nullable=False),
        sa.Column('reference_type', sa.String(), nullable=False),  # retrieval, citation, manual_link
        sa.Column('context', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['source_episode_id'], ['episode.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_episode_id'], ['episode.id'], ondelete='CASCADE')
    )

    # Create indexes
    op.create_index('ix_memory_references_source', 'memory_references', ['source_episode_id'])
    op.create_index('ix_memory_references_target', 'memory_references', ['target_episode_id'])
    op.create_index('ix_memory_references_created_at', 'memory_references', ['created_at'])

    # Create index on importance for faster rescoring queries
    op.create_index('ix_episode_importance', 'episode', ['importance'])
    op.create_index('ix_episode_importance_updated', 'episode', ['importance_last_updated'])


def downgrade():
    op.drop_index('ix_episode_importance_updated')
    op.drop_index('ix_episode_importance')
    op.drop_index('ix_memory_references_created_at')
    op.drop_index('ix_memory_references_target')
    op.drop_index('ix_memory_references_source')
    op.drop_table('memory_references')
    op.drop_column('episode', 'consolidated')
    op.drop_column('episode', 'user_rating')
    # Don't drop access_count and last_accessed as they were not added by this migration
    op.drop_column('episode', 'importance_last_updated')
    op.drop_column('episode', 'base_importance')
