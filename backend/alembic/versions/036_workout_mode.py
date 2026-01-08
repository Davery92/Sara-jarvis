"""Workout Mode - Active workout session tracking

Revision ID: 036_workout_mode
Revises: 035_pattern_correlation
Create Date: 2026-01-04

Creates tables for real-time workout tracking:
- active_workout_session: Tracks current workout state for Sara coaching
- Adds active_session_id column to workout_log for linking sets to sessions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = '036_workout_mode'
down_revision = '035_pattern_correlation'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # ============================================================
    # 1. ACTIVE WORKOUT SESSION TABLE
    # Tracks the user's current workout state for real-time coaching
    # ============================================================
    if not table_exists('active_workout_session'):
        op.create_table(
            'active_workout_session',
            sa.Column('id', sa.String(36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
            sa.Column('template_id', sa.String(36), sa.ForeignKey('fitness_template.id', ondelete='SET NULL'), nullable=True),

            # Session state
            sa.Column('status', sa.String(20), nullable=False, server_default='active'),  # active, paused, completed, abandoned
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),

            # Progress tracking
            sa.Column('current_exercise_index', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('current_set_index', sa.Integer(), nullable=False, server_default='0'),

            # Snapshot of workout at session start (includes weight suggestions)
            # Format: {
            #   "template_name": "Push Day A",
            #   "exercises": [
            #     {
            #       "name": "Bench Press",
            #       "sets": 4,
            #       "reps": "6-8",
            #       "rpe_target": 8,
            #       "suggested_weight": 185,
            #       "progression_note": "Last session felt easy, adding 5lbs",
            #       "last_session": {"weights": [180, 180, 180, 180], "reps": [10, 10, 9, 8], "avg_rpe": 7.5}
            #     }
            #   ]
            # }
            sa.Column('workout_snapshot', JSONB, nullable=True),

            # Rest timer state
            sa.Column('rest_timer_started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('rest_timer_duration_seconds', sa.Integer(), nullable=True),

            # Aggregate stats (updated as sets are logged)
            sa.Column('total_sets_completed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('total_volume', sa.Numeric(12, 2), nullable=False, server_default='0'),  # weight * reps sum

            # Notes
            sa.Column('notes', sa.Text(), nullable=True),

            # Metadata
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        )

        # Index for fast lookup of active session by user
        op.create_index('ix_active_workout_session_user_id', 'active_workout_session', ['user_id'])

        # Partial unique index: only one active session per user
        op.execute("""
            CREATE UNIQUE INDEX ix_active_workout_session_user_active
            ON active_workout_session(user_id)
            WHERE status = 'active'
        """)

        # Index for querying by status
        op.create_index('ix_active_workout_session_status', 'active_workout_session', ['status'])

    # ============================================================
    # 2. ADD active_session_id TO workout_log
    # Links individual sets to their parent active session
    # ============================================================
    if table_exists('workout_log') and not column_exists('workout_log', 'active_session_id'):
        op.add_column(
            'workout_log',
            sa.Column('active_session_id', sa.String(36), nullable=True)
        )

        # Add foreign key constraint
        op.create_foreign_key(
            'fk_workout_log_active_session',
            'workout_log',
            'active_workout_session',
            ['active_session_id'],
            ['id'],
            ondelete='SET NULL'
        )

        # Index for querying sets by session
        op.create_index('ix_workout_log_active_session_id', 'workout_log', ['active_session_id'])


def downgrade() -> None:
    # Remove active_session_id from workout_log
    if table_exists('workout_log') and column_exists('workout_log', 'active_session_id'):
        op.drop_constraint('fk_workout_log_active_session', 'workout_log', type_='foreignkey')
        op.drop_index('ix_workout_log_active_session_id', 'workout_log')
        op.drop_column('workout_log', 'active_session_id')

    # Drop active_workout_session table
    if table_exists('active_workout_session'):
        op.drop_index('ix_active_workout_session_status', 'active_workout_session')
        op.execute('DROP INDEX IF EXISTS ix_active_workout_session_user_active')
        op.drop_index('ix_active_workout_session_user_id', 'active_workout_session')
        op.drop_table('active_workout_session')
