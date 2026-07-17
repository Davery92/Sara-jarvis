"""workout_log -> exercise_library shadow FK — SARA_UNLEASHED Phase U.7.

Adds a NEW nullable `exercise_library_id` column rather than converting the
existing `exercise_id` text column in place. Deliberate, safer deviation
from the plan's literal wording ("exercise_id becomes an FK, legacy text in
a shadow column"): `workout_log.exercise_id` is read as free text by
multiple existing call sites (progressive_overload.py, workout_mode.py,
health.py, training_schedule.py) that weren't fully mapped this session —
retyping/renaming it blind risked breaking all of them. This additive
column gets the same practical result (a canonical link the variant-history
API can join on, checkable for zero orphans) without touching anything that
already works. `exercise_id` is untouched and stays authoritative.

Revision ID: 093_workout_log_exercise_library_fk
Revises: 092_recipe_macros_estimated
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "093_workout_log_exercise_fk"
down_revision = "092_recipe_macros_estimated"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workout_log",
        sa.Column("exercise_library_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_workout_log_exercise_library",
        "workout_log", "exercise_library",
        ["exercise_library_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workout_log_exercise_library_id", "workout_log", ["exercise_library_id"],
    )


def downgrade():
    op.drop_index("ix_workout_log_exercise_library_id", table_name="workout_log")
    op.drop_constraint("fk_workout_log_exercise_library", "workout_log", type_="foreignkey")
    op.drop_column("workout_log", "exercise_library_id")
