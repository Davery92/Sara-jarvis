"""Drop the write-less detected_pattern table.

ProactiveIntelligenceEngine (the only writer) was deleted 2026-07-03 — zero
external callers anywhere, superseded by behavioral_pattern_service.py +
daily_rhythm.py which are actually wired to schedulers. Verified zero rows
in detected_pattern before dropping. The `/api/detected-patterns` route that
read this table is also removed (its only caller, SmartInsightsDashboard.tsx,
was itself never imported/rendered).

Revision ID: 085_drop_detected_pattern
Revises: 084_so_pattern_id_uuid
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func


revision = "085_drop_detected_pattern"
down_revision = "084_so_pattern_id_uuid"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("detected_pattern")


def downgrade():
    op.create_table(
        "detected_pattern",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("pattern_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("pattern_data", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column("data_points", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("related_episodes", sa.Text(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("first_detected", sa.DateTime(timezone=True), server_default=func.now()),
        sa.Column("last_detected", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=func.now()),
    )
