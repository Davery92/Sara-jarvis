"""Add scheduled home actions table

Revision ID: 027_scheduled_home_actions
Revises: 026_home_activity_log
Create Date: 2025-12-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '027_scheduled_home_actions'
down_revision = '026_home_activity_log'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'scheduled_home_action',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('app_user.id'), nullable=False),
        sa.Column('entity_id', sa.String(255), nullable=False),
        sa.Column('domain', sa.String(50), nullable=False),  # light, switch, climate, etc.
        sa.Column('action', sa.String(50), nullable=False),  # turn_on, turn_off, toggle, etc.
        sa.Column('parameters', sa.JSON(), nullable=True),  # brightness, temperature, etc.
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # pending, executed, failed, cancelled
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),  # Human readable description
        sa.Column('recurring', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('recurrence_pattern', sa.String(100), nullable=True),  # daily, weekly, weekdays, weekends, etc.
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # Index for finding pending actions due for execution
    op.create_index(
        'ix_scheduled_home_action_pending',
        'scheduled_home_action',
        ['status', 'scheduled_at'],
        postgresql_where=sa.text("status = 'pending'")
    )

    # Index for user's scheduled actions
    op.create_index(
        'ix_scheduled_home_action_user',
        'scheduled_home_action',
        ['user_id', 'scheduled_at']
    )


def downgrade():
    op.drop_index('ix_scheduled_home_action_user')
    op.drop_index('ix_scheduled_home_action_pending')
    op.drop_table('scheduled_home_action')
