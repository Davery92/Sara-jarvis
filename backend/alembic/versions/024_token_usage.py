"""Add token usage tracking tables

Revision ID: 024_token_usage
Revises: 023_artifacts
Create Date: 2025-12-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '024_token_usage'
down_revision = '023_artifacts'
branch_labels = None
depends_on = None


def upgrade():
    # Create detailed token usage table
    op.create_table('token_usage',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('app_user.id'), nullable=True),
        sa.Column('endpoint', sa.String(255), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('operation_type', sa.String(50), nullable=False),
        sa.Column('prompt_tokens', sa.Integer, nullable=False, default=0),
        sa.Column('completion_tokens', sa.Integer, nullable=False, default=0),
        sa.Column('total_tokens', sa.Integer, nullable=False, default=0),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('request_metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create indexes for efficient querying
    op.create_index('ix_token_usage_user_id', 'token_usage', ['user_id'])
    op.create_index('ix_token_usage_session_id', 'token_usage', ['session_id'])
    op.create_index('ix_token_usage_created_at', 'token_usage', ['created_at'])
    op.create_index('ix_token_usage_user_date', 'token_usage', ['user_id', 'created_at'])

    # Create aggregate table for fast stats
    op.create_table('token_usage_aggregate',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('app_user.id'), nullable=True),
        sa.Column('total_prompt_tokens', sa.BigInteger, nullable=False, default=0),
        sa.Column('total_completion_tokens', sa.BigInteger, nullable=False, default=0),
        sa.Column('total_tokens', sa.BigInteger, nullable=False, default=0),
        sa.Column('total_requests', sa.BigInteger, nullable=False, default=0),
        sa.Column('last_reset_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('ix_token_usage_aggregate_user_id', 'token_usage_aggregate', ['user_id'])


def downgrade():
    op.drop_index('ix_token_usage_aggregate_user_id')
    op.drop_table('token_usage_aggregate')

    op.drop_index('ix_token_usage_user_date')
    op.drop_index('ix_token_usage_created_at')
    op.drop_index('ix_token_usage_session_id')
    op.drop_index('ix_token_usage_user_id')
    op.drop_table('token_usage')
