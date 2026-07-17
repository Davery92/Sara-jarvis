"""Add health_weekly_report table for Sunday-morning weekly health consolidations.

Revision ID: 055_health_weekly_report
Revises: 054_research_plan_origin
Create Date: 2026-05-03

Stores the output of the 3-stage Sunday weekly health pipeline:
recovery analysis → activity (food/workouts) analysis → synthesizer.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = "055_health_weekly_report"
down_revision = "054_research_plan_origin"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table("health_weekly_report"):
        return

    op.create_table(
        "health_weekly_report",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("stats_json", JSONB(), nullable=False),
        sa.Column("recovery_json", JSONB()),
        sa.Column("activity_json", JSONB()),
        sa.Column("headline", sa.String(255)),
        sa.Column("full_markdown", sa.Text()),
        sa.Column("model_used", sa.String(100)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text()),
        sa.Column("push_sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "week_start", name="uq_hwr_user_week"),
    )
    op.create_index("ix_hwr_week_end", "health_weekly_report", ["week_end"])


def downgrade():
    if not _has_table("health_weekly_report"):
        return
    op.drop_index("ix_hwr_week_end", table_name="health_weekly_report")
    op.drop_table("health_weekly_report")
