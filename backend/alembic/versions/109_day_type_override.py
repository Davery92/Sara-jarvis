"""set_day_type override — flip a day to rest/training (Phase 10D).

When Sara (or David) decides "treat today as a rest day", this stores an
explicit override that is_training_day checks first, flipping the nutrition
targets to the rest-day macros.

Revision ID: 109_day_type_override
Revises: 108_scratchpad_entry
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "109_day_type_override"
down_revision = "108_scratchpad_entry"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "day_type_override" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "day_type_override",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("override_date", sa.Date, nullable=False),
        sa.Column("day_type", sa.String(16), nullable=False),  # 'rest' | 'training'
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "override_date", name="uq_day_type_override"),
    )


def downgrade():
    op.drop_table("day_type_override")
