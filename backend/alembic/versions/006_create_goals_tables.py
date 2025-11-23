"""create goals tables

Revision ID: 006_goals_tables
Revises: 005_intelligence_reports
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers
revision = '006_goals_tables'
down_revision = '005_intelligence_reports'
branch_labels = None
depends_on = None


def upgrade():
    # Create goals table
    op.create_table(
        'goal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('goal_type', sa.String(), nullable=False),  # fitness, nutrition, learning, habit, custom
        sa.Column('target_value', sa.Float(), nullable=True),  # Numeric target (e.g., 185 lbs)
        sa.Column('current_value', sa.Float(), nullable=True),  # Current progress
        sa.Column('unit', sa.String(), nullable=True),  # Unit (lbs, reps, hours, etc.)
        sa.Column('target_date', sa.Date(), nullable=True),  # Target completion date
        sa.Column('status', sa.String(), nullable=False, server_default='active'),  # active, completed, abandoned
        sa.Column('priority', sa.Integer(), nullable=True, server_default='5'),  # 1-10 scale
        sa.Column('metadata', JSON, nullable=False, server_default='{}'),  # Additional data
        sa.Column('auto_tracking', sa.Boolean(), nullable=True, server_default='true'),  # Auto-calc progress
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_goal_user_id', 'goal', ['user_id'])
    op.create_index('ix_goal_status', 'goal', ['status'])
    op.create_index('ix_goal_type', 'goal', ['goal_type'])
    op.create_index('ix_goal_user_status', 'goal', ['user_id', 'status'])

    # Create goal_milestone table
    op.create_table(
        'goal_milestone',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('target_value', sa.Float(), nullable=True),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('completed', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['goal_id'], ['goal.id'], ondelete='CASCADE')
    )

    # Create indexes
    op.create_index('ix_goal_milestone_goal_id', 'goal_milestone', ['goal_id'])
    op.create_index('ix_goal_milestone_completed', 'goal_milestone', ['completed'])

    # Create goal_progress table (manual + auto-tracked progress)
    op.create_table(
        'goal_progress',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),  # Progress value
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),  # manual, auto, event
        sa.Column('source_id', sa.String(), nullable=True),  # ID of source event (e.g., workout_log.id)
        sa.Column('logged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['goal_id'], ['goal.id'], ondelete='CASCADE')
    )

    # Create indexes
    op.create_index('ix_goal_progress_goal_id', 'goal_progress', ['goal_id'])
    op.create_index('ix_goal_progress_logged_at', 'goal_progress', ['logged_at'])
    op.create_index('ix_goal_progress_source', 'goal_progress', ['source', 'source_id'])


def downgrade():
    op.drop_table('goal_progress')
    op.drop_table('goal_milestone')
    op.drop_table('goal')
