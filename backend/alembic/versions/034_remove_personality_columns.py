"""Remove personality mode columns

Revision ID: 034_remove_personality
Revises: 033_shadow_agent_rebuild
Create Date: 2024-12-27

Removes unused personality_mode and current_mode columns from:
- autonomous_insight.personality_mode
- background_sweep.personality_mode
- user_profile.current_mode
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '034_remove_personality'
down_revision = '033_shadow_agent_rebuild'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    bind = op.get_bind()
    insp = inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Remove personality_mode from autonomous_insight if it exists
    if column_exists('autonomous_insight', 'personality_mode'):
        op.drop_column('autonomous_insight', 'personality_mode')

    # Remove personality_mode from background_sweep if it exists
    if column_exists('background_sweep', 'personality_mode'):
        op.drop_column('background_sweep', 'personality_mode')

    # Remove current_mode from user_profile if it exists
    if column_exists('user_profile', 'current_mode'):
        op.drop_column('user_profile', 'current_mode')


def downgrade():
    # Re-add columns if needed
    if not column_exists('autonomous_insight', 'personality_mode'):
        op.add_column('autonomous_insight',
            sa.Column('personality_mode', sa.String(), nullable=True, server_default='standard'))

    if not column_exists('background_sweep', 'personality_mode'):
        op.add_column('background_sweep',
            sa.Column('personality_mode', sa.String(), nullable=True, server_default='standard'))

    if not column_exists('user_profile', 'current_mode'):
        op.add_column('user_profile',
            sa.Column('current_mode', sa.String(), nullable=True, server_default='companion'))
