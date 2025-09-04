"""Fitness module initial schema and calendar extensions

Revision ID: 20250901_fitness_scaffold
Revises: 20250830_memory_stack
Create Date: 2025-09-01 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250901_fitness_scaffold'
down_revision: Union[str, Sequence[str], None] = '20250830_memory_stack'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fitness core tables (String IDs for cross-db compatibility)
    op.create_table(
        'fitness_profile',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('demographics', sa.JSON(), nullable=True),
        sa.Column('equipment', sa.JSON(), nullable=True),
        sa.Column('preferences', sa.JSON(), nullable=True),
        sa.Column('constraints', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'fitness_goal',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('goal_type', sa.String(), nullable=False),
        sa.Column('targets', sa.JSON(), nullable=True),
        sa.Column('timeframe', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'fitness_plan',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'workout',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('plan_id', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=True),
        sa.Column('week', sa.Integer(), nullable=True),
        sa.Column('day_of_week', sa.Integer(), nullable=True),
        sa.Column('duration_min', sa.Integer(), nullable=True),
        sa.Column('prescription', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('calendar_event_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'workout_log',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('workout_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('exercise_id', sa.String(), nullable=True),
        sa.Column('set_index', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=True),
        sa.Column('reps', sa.Integer(), nullable=True),
        sa.Column('rpe', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('flags', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'morning_readiness',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('hrv_ms', sa.Integer(), nullable=True),
        sa.Column('rhr', sa.Integer(), nullable=True),
        sa.Column('sleep_hours', sa.Integer(), nullable=True),
        sa.Column('energy', sa.Integer(), nullable=False),
        sa.Column('soreness', sa.Integer(), nullable=False),
        sa.Column('stress', sa.Integer(), nullable=False),
        sa.Column('time_available_min', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('recommendation', sa.String(), nullable=False),
        sa.Column('adjustments', sa.JSON(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )

    op.create_table(
        'fitness_idempotency',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('client_txn_id', sa.String(), index=True, nullable=False),
        sa.Column('hash', sa.String(), nullable=True),
        sa.Column('applied_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('succeeded', sa.Boolean(), server_default=sa.text('true'), nullable=True),
    )

    # Calendar extensions for fitness integration
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if 'event' not in tables:
        # Create minimal calendar event table compatible with existing app_user schema (string IDs)
        op.create_table(
            'event',
            sa.Column('id', sa.String(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.String(), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('location', sa.String(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('source', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('meta', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')), 
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        )
    else:
        with op.batch_alter_table('event') as batch_op:
            batch_op.add_column(sa.Column('source', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('status', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('meta', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('event') as batch_op:
        batch_op.drop_column('meta')
        batch_op.drop_column('status')
        batch_op.drop_column('source')

    op.drop_table('fitness_idempotency')
    op.drop_table('morning_readiness')
    op.drop_table('workout_log')
    op.drop_table('workout')
    op.drop_table('fitness_plan')
    op.drop_table('fitness_goal')
    op.drop_table('fitness_profile')
