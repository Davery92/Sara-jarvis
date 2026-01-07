"""Add activity metrics columns to machine table

Revision ID: 038_machine_activity_metrics
Revises: 037_user_settings
Create Date: 2025-01-07

Adds detailed activity tracking columns to the machine table:
- keyboard_events_total / keyboard_events_recent
- mouse_events_total / mouse_events_recent
- active_window / active_app
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '038_machine_activity_metrics'
down_revision = '037_user_settings'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    bind = op.get_bind()
    insp = inspect(bind)
    try:
        columns = [c['name'] for c in insp.get_columns(table_name)]
        return column_name in columns
    except Exception:
        return False


def table_exists(table_name):
    """Check if a table exists"""
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade():
    if not table_exists('machine'):
        return

    # Add keyboard event columns
    if not column_exists('machine', 'keyboard_events_total'):
        op.add_column('machine',
            sa.Column('keyboard_events_total', sa.Integer(), server_default='0'))

    if not column_exists('machine', 'keyboard_events_recent'):
        op.add_column('machine',
            sa.Column('keyboard_events_recent', sa.Integer(), server_default='0'))

    # Add mouse event columns
    if not column_exists('machine', 'mouse_events_total'):
        op.add_column('machine',
            sa.Column('mouse_events_total', sa.Integer(), server_default='0'))

    if not column_exists('machine', 'mouse_events_recent'):
        op.add_column('machine',
            sa.Column('mouse_events_recent', sa.Integer(), server_default='0'))

    # Add active window/app columns
    if not column_exists('machine', 'active_window'):
        op.add_column('machine',
            sa.Column('active_window', sa.String(), nullable=True))

    if not column_exists('machine', 'active_app'):
        op.add_column('machine',
            sa.Column('active_app', sa.String(), nullable=True))


def downgrade():
    if not table_exists('machine'):
        return

    columns_to_drop = [
        'keyboard_events_total',
        'keyboard_events_recent',
        'mouse_events_total',
        'mouse_events_recent',
        'active_window',
        'active_app'
    ]

    for col in columns_to_drop:
        if column_exists('machine', col):
            op.drop_column('machine', col)
