"""Add user settings table

Revision ID: 037_user_settings
Revises: 036_workout_mode
Create Date: 2025-01-07

Adds user_settings table for storing user preferences including:
- Vision model configuration
- Screenshot settings
- Desktop agent settings
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = '037_user_settings'
down_revision = '036_workout_mode'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists"""
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade():
    if not table_exists('user_settings'):
        op.create_table(
            'user_settings',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),

            # Vision settings
            sa.Column('vision_model', sa.String(), server_default='qwen3-vl:latest'),
            sa.Column('vision_endpoint', sa.String(), server_default='http://10.185.1.8:11434'),

            # Screenshot settings
            sa.Column('screenshot_enabled', sa.Boolean(), server_default='true'),
            sa.Column('screenshot_interval_seconds', sa.Integer(), server_default='30'),
            sa.Column('screenshot_blur_sensitive', sa.Boolean(), server_default='true'),

            # Desktop agent settings
            sa.Column('wake_word_enabled', sa.Boolean(), server_default='true'),
            sa.Column('activity_tracking_enabled', sa.Boolean(), server_default='true'),
            sa.Column('cross_device_commands_enabled', sa.Boolean(), server_default='true'),

            # Flexible preferences
            sa.Column('preferences', JSONB(), server_default='{}'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),

            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('user_id')
        )

        # Create index on user_id
        op.create_index('ix_user_settings_user_id', 'user_settings', ['user_id'])


def downgrade():
    if table_exists('user_settings'):
        op.drop_index('ix_user_settings_user_id', 'user_settings')
        op.drop_table('user_settings')
