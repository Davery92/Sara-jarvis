"""Add artifacts table for canvas system

Revision ID: 023_artifacts
Revises: 022_project_files
Create Date: 2025-12-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '023_artifacts'
down_revision = '022_project_files'
branch_labels = None
depends_on = None


def upgrade():
    # Create artifacts table
    op.create_table('artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), nullable=True),
        sa.Column('episode_id', sa.String(36), nullable=True),
        sa.Column('artifact_type', sa.String(50), nullable=False),  # code, diagram, document, canvas, table
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('content', postgresql.JSONB, nullable=False),  # Flexible content storage
        sa.Column('artifact_metadata', postgresql.JSONB, nullable=True),  # version, language, etc.
        sa.Column('is_pinned', sa.Boolean, default=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create indexes for efficient querying
    op.create_index('ix_artifacts_user_id', 'artifacts', ['user_id'])
    op.create_index('ix_artifacts_user_conversation', 'artifacts', ['user_id', 'conversation_id'])
    op.create_index('ix_artifacts_type', 'artifacts', ['artifact_type'])
    op.create_index('ix_artifacts_created_at', 'artifacts', ['created_at'])


def downgrade():
    op.drop_index('ix_artifacts_created_at')
    op.drop_index('ix_artifacts_type')
    op.drop_index('ix_artifacts_user_conversation')
    op.drop_index('ix_artifacts_user_id')
    op.drop_table('artifacts')
