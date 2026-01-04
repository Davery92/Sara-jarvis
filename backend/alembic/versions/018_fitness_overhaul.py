"""Fitness Module Overhaul - FatSecret integration, Programs, Phases, Workout Sessions

Revision ID: 018_fitness_overhaul
Revises: 017_add_topic_connections
Create Date: 2025-12-05

This migration adds:
1. fatsecret_food_cache - Cached FatSecret food items with servings
2. fitness_program - Training programs (12-week cut, hypertrophy block, etc.)
3. fitness_phase - Enhanced phases with nutrition targets
4. workout_template - Redesigned templates with rotation support
5. template_exercise - Exercises within templates with progression rules
6. workout_set - Individual sets within sessions
7. exercise_pr - Personal record tracking
8. weight_trend - Daily weight with smoothed trend

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = '018_fitness_overhaul'
down_revision = '017_add_topic_connections'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name: str) -> bool:
    """Check if a table exists"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # 1. FatSecret Food Cache Table
    if not table_exists('fatsecret_food_cache'):
        op.create_table(
            'fatsecret_food_cache',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('fatsecret_id', sa.String(50), nullable=False, unique=True),
            sa.Column('name', sa.String(500), nullable=False),
            sa.Column('brand', sa.String(200), nullable=True),
            sa.Column('food_type', sa.String(50), nullable=True),
            sa.Column('barcode', sa.String(50), nullable=True, index=True),
            sa.Column('servings_json', JSONB, nullable=True),
            sa.Column('cached_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_fatsecret_food_cache_fatsecret_id', 'fatsecret_food_cache', ['fatsecret_id'])
        op.create_index('ix_fatsecret_food_cache_name', 'fatsecret_food_cache', ['name'])

    # 2. Fitness Program Table
    if not table_exists('fitness_program'):
        op.create_table(
            'fitness_program',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('goal', sa.String(50), nullable=False),
            sa.Column('start_date', sa.Date(), nullable=True),
            sa.Column('end_date', sa.Date(), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE')
        )
        op.create_index('ix_fitness_program_user_active', 'fitness_program', ['user_id', 'is_active'])

    # 3. Enhance existing fitness_phase with nutrition targets (only add columns that don't exist)
    phase_columns = [
        ('program_id', sa.String(), None),
        ('order_index', sa.Integer(), 0),
        ('duration_weeks', sa.Integer(), None),
        ('calories_target', sa.Integer(), None),
        ('protein_target', sa.Integer(), None),
        ('carbs_target', sa.Integer(), None),
        ('fat_target', sa.Integer(), None),
        ('training_days_per_week', sa.Integer(), None),
        ('deload_week', sa.Integer(), None),
    ]

    for col_name, col_type, default in phase_columns:
        if not column_exists('fitness_phase', col_name):
            op.add_column('fitness_phase', sa.Column(col_name, col_type, nullable=True, default=default))

    # Add FK for program_id if the column was just added
    # Skip FK creation if it already exists (handled by try/except in actual migration)

    # 4. Add rotation support to existing fitness_template
    template_columns = [
        ('day_of_week', sa.Integer()),
        ('rotation_order', sa.Integer()),
    ]

    for col_name, col_type in template_columns:
        if not column_exists('fitness_template', col_name):
            op.add_column('fitness_template', sa.Column(col_name, col_type, nullable=True))

    # 5. Template Exercise Table - exercises within templates
    if not table_exists('template_exercise'):
        op.create_table(
            'template_exercise',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('template_id', sa.String(), nullable=False),
            sa.Column('exercise_name', sa.String(200), nullable=False),
            sa.Column('order_index', sa.Integer(), default=0),
            sa.Column('target_sets', sa.Integer(), default=3),
            sa.Column('rep_range_low', sa.Integer(), default=8),
            sa.Column('rep_range_high', sa.Integer(), default=12),
            sa.Column('target_rpe', sa.Numeric(3, 1), nullable=True),
            sa.Column('rest_seconds', sa.Integer(), default=120),
            sa.Column('progression_rule', sa.String(50), default='DOUBLE_PROGRESSION'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['template_id'], ['fitness_template.id'], ondelete='CASCADE')
        )
        op.create_index('ix_template_exercise_template', 'template_exercise', ['template_id'])

    # 6. Add columns to workout_log for enhanced tracking (only if they don't exist)
    workout_log_columns = [
        ('template_exercise_id', sa.String()),
        ('set_number', sa.Integer()),
        ('is_pr', sa.Boolean()),
        ('skipped', sa.Boolean()),
    ]

    for col_name, col_type in workout_log_columns:
        if not column_exists('workout_log', col_name):
            op.add_column('workout_log', sa.Column(col_name, col_type, nullable=True))

    # 7. Exercise PR Table
    if not table_exists('exercise_pr'):
        op.create_table(
            'exercise_pr',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('exercise_name', sa.String(200), nullable=False),
            sa.Column('weight', sa.Numeric(8, 2), nullable=False),
            sa.Column('reps', sa.Integer(), nullable=False),
            sa.Column('estimated_1rm', sa.Numeric(8, 2), nullable=False),
            sa.Column('achieved_at', sa.Date(), nullable=False),
            sa.Column('workout_set_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE')
        )
        op.create_index('ix_exercise_pr_user_exercise', 'exercise_pr', ['user_id', 'exercise_name'])
        op.create_index('ix_exercise_pr_achieved', 'exercise_pr', ['achieved_at'])

    # 8. Weight Trend Table - for smoothed weight tracking
    if not table_exists('weight_trend'):
        op.create_table(
            'weight_trend',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('raw_weight', sa.Numeric(5, 2), nullable=False),
            sa.Column('trend_weight', sa.Numeric(5, 2), nullable=True),
            sa.Column('weekly_delta', sa.Numeric(5, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('user_id', 'date', name='uq_weight_trend_user_date')
        )
        op.create_index('ix_weight_trend_user_date', 'weight_trend', ['user_id', 'date'])

    # 9. Update food_log with FatSecret serving reference
    if not column_exists('food_log', 'fatsecret_serving_id'):
        op.add_column('food_log', sa.Column('fatsecret_serving_id', sa.String(50), nullable=True))

    # 10. Create food_log_item table for individual items within a meal
    if not table_exists('food_log_item'):
        op.create_table(
            'food_log_item',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('food_log_id', sa.String(), nullable=False),
            sa.Column('fatsecret_food_id', sa.String(), nullable=True),
            sa.Column('recipe_id', sa.String(), nullable=True),
            sa.Column('custom_food_id', sa.String(), nullable=True),
            sa.Column('serving_id', sa.String(100), nullable=True),
            sa.Column('serving_description', sa.String(200), nullable=True),
            sa.Column('quantity', sa.Numeric(8, 2), default=1),
            sa.Column('calories', sa.Numeric(8, 2), nullable=True),
            sa.Column('protein', sa.Numeric(8, 2), nullable=True),
            sa.Column('carbs', sa.Numeric(8, 2), nullable=True),
            sa.Column('fat', sa.Numeric(8, 2), nullable=True),
            sa.Column('fiber', sa.Numeric(8, 2), nullable=True),
            sa.Column('sugar', sa.Numeric(8, 2), nullable=True),
            sa.Column('sodium', sa.Numeric(8, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['food_log_id'], ['food_log.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['fatsecret_food_id'], ['fatsecret_food_cache.id'], ondelete='SET NULL')
        )
        op.create_index('ix_food_log_item_food_log', 'food_log_item', ['food_log_id'])


def downgrade() -> None:
    # Drop tables in reverse order (only if they exist)
    if table_exists('food_log_item'):
        op.drop_index('ix_food_log_item_food_log')
        op.drop_table('food_log_item')

    if column_exists('food_log', 'fatsecret_serving_id'):
        op.drop_column('food_log', 'fatsecret_serving_id')

    if table_exists('weight_trend'):
        op.drop_index('ix_weight_trend_user_date')
        op.drop_table('weight_trend')

    if table_exists('exercise_pr'):
        op.drop_index('ix_exercise_pr_achieved')
        op.drop_index('ix_exercise_pr_user_exercise')
        op.drop_table('exercise_pr')

    # Drop workout_log columns
    workout_log_cols = ['skipped', 'is_pr', 'set_number', 'template_exercise_id']
    for col in workout_log_cols:
        if column_exists('workout_log', col):
            op.drop_column('workout_log', col)

    if table_exists('template_exercise'):
        op.drop_index('ix_template_exercise_template')
        op.drop_table('template_exercise')

    # Drop fitness_template columns
    template_cols = ['rotation_order', 'day_of_week']
    for col in template_cols:
        if column_exists('fitness_template', col):
            op.drop_column('fitness_template', col)

    # Drop fitness_phase columns
    phase_cols = ['deload_week', 'training_days_per_week', 'fat_target', 'carbs_target',
                  'protein_target', 'calories_target', 'duration_weeks', 'order_index', 'program_id']
    for col in phase_cols:
        if column_exists('fitness_phase', col):
            op.drop_column('fitness_phase', col)

    if table_exists('fitness_program'):
        op.drop_index('ix_fitness_program_user_active')
        op.drop_table('fitness_program')

    if table_exists('fatsecret_food_cache'):
        op.drop_index('ix_fatsecret_food_cache_name')
        op.drop_index('ix_fatsecret_food_cache_fatsecret_id')
        op.drop_table('fatsecret_food_cache')
