"""add insight mention log

Revision ID: 011_insight_mention
Revises: 010_episode_rating
Create Date: 2025-11-25 02:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_insight_mention'
down_revision = '010_episode_rating'
branch_labels = None
depends_on = None


def upgrade():
    # Create insight_mention_log table
    op.create_table(
        'insight_mention_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('insight_id', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), nullable=True),
        sa.Column('mentioned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('user_engaged', sa.Boolean(), default=False, nullable=False),
        sa.Column('engagement_type', sa.String(), nullable=True),  # positive, neutral, negative, ignored
        sa.Column('engaged_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['insight_id'], ['dream_insight.id'], ondelete='CASCADE')
    )

    # Create indexes for efficient querying
    op.create_index('idx_insight_mention_user', 'insight_mention_log', ['user_id', 'mentioned_at'])
    op.create_index('idx_insight_mention_insight', 'insight_mention_log', ['insight_id'])
    op.create_index('idx_insight_mention_conversation', 'insight_mention_log', ['conversation_id'])


def downgrade():
    op.drop_index('idx_insight_mention_conversation', table_name='insight_mention_log')
    op.drop_index('idx_insight_mention_insight', table_name='insight_mention_log')
    op.drop_index('idx_insight_mention_user', table_name='insight_mention_log')
    op.drop_table('insight_mention_log')
