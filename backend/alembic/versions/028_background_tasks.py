"""Add background tasks table for agent orchestration

Revision ID: 028_background_tasks
Revises: 027_scheduled_home_actions
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '028_background_tasks'
down_revision = '027_scheduled_home_actions'
branch_labels = None
depends_on = None


def upgrade():
    # Create background_task table for tracking agent tasks
    op.create_table('background_task',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='pending'),
        sa.Column('task_type', sa.String(100), nullable=False, default='research'),
        sa.Column('original_query', sa.Text, nullable=False),
        sa.Column('result_note_id', sa.String(36), nullable=True),
        sa.Column('workspace_folder_id', sa.String(36), nullable=True),
        sa.Column('clarification_question', sa.Text, nullable=True),
        sa.Column('clarification_response', sa.Text, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('task_metadata', postgresql.JSONB, nullable=True, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create indexes for efficient querying
    op.create_index('ix_background_task_user_id', 'background_task', ['user_id'])
    op.create_index('ix_background_task_status', 'background_task', ['status'])
    op.create_index('ix_background_task_user_status', 'background_task', ['user_id', 'status'])
    op.create_index('ix_background_task_created_at', 'background_task', ['created_at'])


def downgrade():
    op.drop_index('ix_background_task_created_at')
    op.drop_index('ix_background_task_user_status')
    op.drop_index('ix_background_task_status')
    op.drop_index('ix_background_task_user_id')
    op.drop_table('background_task')
