"""Fix standing_order.pattern_id type mismatch blocking pattern promotion.

`behavioral_pattern.id` is a uuid (gen_random_uuid()), but `standing_order.pattern_id`
was declared integer — so any promote_pattern() INSERT would fail with
"invalid input syntax for type integer". This path had never carried live
traffic (per the July 3 audit) so the mismatch was never hit in production.

Revision ID: 084_so_pattern_id_uuid
Revises: 083_daily_rhythm
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "084_so_pattern_id_uuid"
down_revision = "083_daily_rhythm"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "standing_order", "pattern_id",
        existing_type=sa.Integer(),
        type_=sa.String(),
        postgresql_using="pattern_id::varchar",
    )


def downgrade():
    op.alter_column(
        "standing_order", "pattern_id",
        existing_type=sa.String(),
        type_=sa.Integer(),
        postgresql_using="NULL",  # existing uuid values can't downcast; drop them
    )
