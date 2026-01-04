"""Add topic_connection table for cross-topic relationships

Revision ID: 017_add_topic_connections
Revises: 016_add_learning_system_tables
Create Date: 2025-12-04

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017_add_topic_connections'
down_revision = '016_learning_system'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'topic_connection',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('source_topic_id', sa.String(), nullable=False),
        sa.Column('target_topic_id', sa.String(), nullable=False),
        sa.Column('connection_type', sa.String(50), nullable=False),
        sa.Column('strength', sa.Float(), default=0.5),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('auto_generated', sa.Boolean(), default=False),
        sa.Column('confirmed', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_topic_id'], ['learning_topic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_topic_id'], ['learning_topic.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'source_topic_id', 'target_topic_id', 'connection_type',
                           name='uq_topic_connection_pair')
    )

    # Create indexes for fast lookups
    op.create_index('ix_topic_connection_source', 'topic_connection', ['source_topic_id'])
    op.create_index('ix_topic_connection_target', 'topic_connection', ['target_topic_id'])
    op.create_index('ix_topic_connection_user', 'topic_connection', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_topic_connection_user')
    op.drop_index('ix_topic_connection_target')
    op.drop_index('ix_topic_connection_source')
    op.drop_table('topic_connection')
