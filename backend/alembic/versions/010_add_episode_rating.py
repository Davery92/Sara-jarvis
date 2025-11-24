"""Add episode rating system

Revision ID: 010_add_episode_rating
Revises: 009_migrate_episode_embedding_to_vector
Create Date: 2025-01-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010_episode_rating'
down_revision = '009_episode_vector'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create episode_rating table
    op.create_table(
        'episode_rating',
        sa.Column('episode_id', sa.String(), nullable=False),
        sa.Column('user_rating', sa.Integer(), nullable=True, comment='User rating 1-5 stars'),
        sa.Column('rating_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('average_rating', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('rating_sum', sa.Integer(), nullable=False, server_default='0', comment='Sum of all ratings'),
        sa.Column('last_rated', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('episode_id'),
        sa.ForeignKeyConstraint(['episode_id'], ['episode.id'], ondelete='CASCADE')
    )

    # Create indexes for efficient queries
    op.create_index('idx_episode_rating_last_rated', 'episode_rating', ['last_rated'])
    op.create_index('idx_episode_rating_avg', 'episode_rating', ['average_rating'])

    # Add rating columns to episode table
    op.add_column('episode', sa.Column('rating_boost', sa.Float(), nullable=False, server_default='0.0',
                                       comment='Pre-computed rating boost for retrieval (Wilson + decay)'))
    op.add_column('episode', sa.Column('exploration_bonus', sa.Float(), nullable=False, server_default='0.0',
                                       comment='Thompson Sampling exploration bonus for cold-start'))

    # Create indexes on new episode columns
    op.create_index('idx_episode_rating_boost', 'episode', ['rating_boost'])
    op.create_index('idx_episode_exploration_bonus', 'episode', ['exploration_bonus'])

    # Create composite index for retrieval queries (user_id + created_at + rating_boost)
    op.create_index('idx_episode_user_created_rating', 'episode', ['user_id', 'created_at', 'rating_boost'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_episode_user_created_rating', table_name='episode')
    op.drop_index('idx_episode_exploration_bonus', table_name='episode')
    op.drop_index('idx_episode_rating_boost', table_name='episode')
    op.drop_index('idx_episode_rating_avg', table_name='episode_rating')
    op.drop_index('idx_episode_rating_last_rated', table_name='episode_rating')

    # Drop columns from episode table
    op.drop_column('episode', 'exploration_bonus')
    op.drop_column('episode', 'rating_boost')

    # Drop episode_rating table
    op.drop_table('episode_rating')
