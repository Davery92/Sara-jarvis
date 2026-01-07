"""Add shadow session table

Revision ID: 039_shadow_session
Revises: 038_machine_activity_metrics
Create Date: 2026-01-07

Adds ShadowSession table for tracking active shadow monitoring sessions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '039_shadow_session'
down_revision = '038_machine_activity_metrics'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists"""
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade():
    # Create shadow_session table if it doesn't exist
    if not table_exists('shadow_session'):
        op.create_table(
            'shadow_session',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('machine_id', sa.String(), sa.ForeignKey('machine.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.String(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('session_type', sa.String(), default='standard'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_shadow_session_machine_id', 'shadow_session', ['machine_id'])
        op.create_index('ix_shadow_session_user_id', 'shadow_session', ['user_id'])
        op.create_index('ix_shadow_session_is_active', 'shadow_session', ['is_active'])

    # Create shadow_screenshot table if it doesn't exist
    if not table_exists('shadow_screenshot'):
        op.create_table(
            'shadow_screenshot',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('session_id', sa.String(), sa.ForeignKey('shadow_session.id', ondelete='CASCADE'), nullable=True),
            sa.Column('minio_key', sa.String(), nullable=False),
            sa.Column('file_size_bytes', sa.Integer(), nullable=True),
            sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('window_title', sa.String(), nullable=True),
            sa.Column('app_name', sa.String(), nullable=True),
            sa.Column('image_hash', sa.String(), nullable=True),
            sa.Column('was_blurred', sa.Boolean(), default=False),
            sa.Column('blur_reason', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_shadow_screenshot_session_id', 'shadow_screenshot', ['session_id'])


def downgrade():
    if table_exists('shadow_screenshot'):
        op.drop_table('shadow_screenshot')
    if table_exists('shadow_session'):
        op.drop_table('shadow_session')
