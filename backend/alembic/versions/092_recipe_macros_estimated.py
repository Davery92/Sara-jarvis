"""Recipe macros_estimated flag — SARA_UNLEASHED Phase U.6.

R27: recipes save without nutrition — recipes_create accepts calories as
optional and nothing computes it from the structured ingredients even
though FatSecret lookup + food_database cache exist two tools away. This
adds the flag distinguishing computed-from-ingredients macros from
hand-entered ones, so the estimator never overwrites a real value.

Revision ID: 092_recipe_macros_estimated
Revises: 091_drop_habits_tables
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "092_recipe_macros_estimated"
down_revision = "091_drop_habits_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recipe",
        sa.Column("macros_estimated", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("recipe", "macros_estimated")
