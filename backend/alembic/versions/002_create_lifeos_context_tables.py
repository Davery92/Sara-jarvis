"""create lifeos context tables

Revision ID: 002_lifeos_context
Revises: 001_event_log
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '002_lifeos_context'
down_revision = '001_event_log'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_life_context table
    op.create_table(
        'user_life_context',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('active_goals', JSON, nullable=False, server_default='[]'),
        sa.Column('current_habits', JSON, nullable=False, server_default='[]'),
        sa.Column('current_projects', JSON, nullable=False, server_default='[]'),
        sa.Column('health_status', JSON, nullable=False, server_default='{}'),
        sa.Column('focus_mode', sa.String(), nullable=True),  # work, fitness, personal, learning
        sa.Column('stress_level', sa.Integer(), nullable=True),  # 1-10 scale
        sa.Column('mood_profile', JSON, nullable=False, server_default='{}'),
        sa.Column('energy_level', sa.Integer(), nullable=True),  # 1-10 scale
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_user_life_context_user_id', 'user_life_context', ['user_id'], unique=True)

    # Create context_snapshots table (for historical tracking)
    op.create_table(
        'context_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('snapshot_data', JSON, nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_context_snapshots_user_id', 'context_snapshots', ['user_id'])
    op.create_index('ix_context_snapshots_snapshot_date', 'context_snapshots', ['snapshot_date'])
    op.create_index('ix_context_snapshots_user_date', 'context_snapshots', ['user_id', 'snapshot_date'], unique=True)


def downgrade():
    op.drop_table('context_snapshots')
    op.drop_table('user_life_context')
