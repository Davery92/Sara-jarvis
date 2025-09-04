"""Add fitness exercise library and readiness adjustments tables

Revision ID: 20250902_fitness_extensions
Revises: 20250902_normalize_reminders_timers
Create Date: 2025-09-02 10:13:37

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '20250902_fitness_extensions'
down_revision: Union[str, Sequence[str], None] = '20250902_normalize_rt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Exercise library table for movement patterns and substitutions
    op.create_table(
        'exercise_library',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('movement_pattern', sa.String(), nullable=False),  # squat, hinge, press, pull, etc.
        sa.Column('muscle_groups', sa.JSON(), nullable=True),  # primary and secondary muscles
        sa.Column('equipment_required', sa.JSON(), nullable=True),  # list of equipment needed
        sa.Column('equipment_alternatives', sa.JSON(), nullable=True),  # alternative equipment options
        sa.Column('difficulty_level', sa.Integer(), nullable=True),  # 1-5 scale
        sa.Column('injury_contraindications', sa.JSON(), nullable=True),  # list of injuries that preclude this
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('instructions', sa.JSON(), nullable=True),  # setup, execution, cues
        sa.Column('substitutions', sa.JSON(), nullable=True),  # list of exercise IDs that can substitute
        sa.Column('tags', sa.JSON(), nullable=True),  # compound, isolation, unilateral, etc.
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # Create index on movement pattern for fast substitution lookups
    op.create_index('ix_exercise_library_movement_pattern', 'exercise_library', ['movement_pattern'])
    
    # Movement patterns categorization table
    op.create_table(
        'movement_patterns',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('pattern_name', sa.String(), nullable=False, unique=True),  # squat, hinge, press, etc.
        sa.Column('pattern_type', sa.String(), nullable=False),  # lower, upper, core, locomotion
        sa.Column('primary_muscles', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('progression_hierarchy', sa.JSON(), nullable=True),  # beginner → advanced exercises
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # Readiness adjustments log table for tracking what changes were made
    op.create_table(
        'readiness_adjustments',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('readiness_id', sa.String(), sa.ForeignKey('morning_readiness.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workout_id', sa.String(), sa.ForeignKey('workout.id', ondelete='CASCADE'), nullable=False),
        sa.Column('adjustment_type', sa.String(), nullable=False),  # keep, reduce, swap, move
        sa.Column('original_prescription', sa.JSON(), nullable=True),  # backup of original workout
        sa.Column('adjusted_prescription', sa.JSON(), nullable=True),  # what it was changed to
        sa.Column('reasoning', sa.Text(), nullable=True),  # why this adjustment was made
        sa.Column('applied_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # Plan templates table for storing reusable workout plans
    op.create_table(
        'plan_templates',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('template_type', sa.String(), nullable=False),  # full_body, upper_lower, ppl, etc.
        sa.Column('days_per_week', sa.Integer(), nullable=False),
        sa.Column('weeks_per_phase', sa.Integer(), nullable=True),
        sa.Column('phases', sa.JSON(), nullable=False),  # phase definitions and progressions
        sa.Column('equipment_required', sa.JSON(), nullable=True),
        sa.Column('difficulty_level', sa.Integer(), nullable=True),
        sa.Column('primary_goals', sa.JSON(), nullable=True),  # strength, hypertrophy, endurance
        sa.Column('workout_templates', sa.JSON(), nullable=False),  # actual workout structures
        sa.Column('substitution_rules', sa.JSON(), nullable=True),  # equipment-based substitutions
        sa.Column('progression_rules', sa.JSON(), nullable=True),  # how to progress loads/reps
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # User readiness baselines for calculating personalized scores
    op.create_table(
        'readiness_baselines',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False, unique=True),
        sa.Column('hrv_baseline', sa.Float(), nullable=True),  # EWMA of HRV readings
        sa.Column('hrv_std_dev', sa.Float(), nullable=True),
        sa.Column('rhr_baseline', sa.Float(), nullable=True),  # EWMA of resting HR
        sa.Column('rhr_std_dev', sa.Float(), nullable=True),
        sa.Column('sleep_baseline', sa.Float(), nullable=True),  # EWMA of sleep hours
        sa.Column('baseline_period_days', sa.Integer(), default=14, nullable=True),
        sa.Column('last_calculated', sa.DateTime(), nullable=True),
        sa.Column('sample_count', sa.Integer(), default=0, nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # Workout session state for in-workout tracking
    op.create_table(
        'workout_sessions',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('workout_id', sa.String(), sa.ForeignKey('workout.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('session_state', sa.String(), nullable=False, default='idle'),  # idle, warmup, working_set, resting, summary, completed
        sa.Column('current_block_index', sa.Integer(), default=0, nullable=True),
        sa.Column('current_exercise_index', sa.Integer(), default=0, nullable=True),
        sa.Column('current_set_index', sa.Integer(), default=0, nullable=True),
        sa.Column('rest_timer_ends_at', sa.DateTime(), nullable=True),
        sa.Column('session_data', sa.JSON(), nullable=True),  # current prescription, modifications, etc.
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    
    # Create unique index to prevent multiple active sessions per workout
    op.create_index('ix_workout_sessions_workout_active', 'workout_sessions', ['workout_id', 'session_state'])


def downgrade() -> None:
    op.drop_index('ix_workout_sessions_workout_active')
    op.drop_table('workout_sessions')
    op.drop_table('readiness_baselines')
    op.drop_table('plan_templates')
    op.drop_table('readiness_adjustments')
    op.drop_table('movement_patterns')
    op.drop_index('ix_exercise_library_movement_pattern')
    op.drop_table('exercise_library')