"""Add external_workout table for HealthKit/Apple-Watch logged workouts.

Revision ID: 056_external_workout
Revises: 055_health_weekly_report
Create Date: 2026-05-05

Stores workouts ingested from external sources (Apple Health initially) so
they don't mix with the manually-tracked workout_sessions / workout_log
tables that hold David's app-logged strength sessions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect


revision = "056_external_workout"
down_revision = "055_health_weekly_report"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table("external_workout"):
        return

    op.create_table(
        "external_workout",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="apple_health"),
        # external_id = HKWorkout UUID (or equivalent stable id from the source).
        # Combined with source, used for upsert dedup so re-syncs don't multiply rows.
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("activity_type", sa.String(80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("total_energy_kcal", sa.Numeric(10, 2)),
        sa.Column("total_distance_m", sa.Numeric(12, 2)),
        sa.Column("avg_heart_rate", sa.Integer),
        sa.Column("max_heart_rate", sa.Integer),
        sa.Column("min_heart_rate", sa.Integer),
        # hr_zones: {"zone_1": minutes, "zone_2": minutes, ...} based on % of max HR
        sa.Column("hr_zones", JSONB),
        # metadata: {"device": "Apple Watch", "indoor": false, "elevation_m": 42, ...}
        sa.Column("workout_metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index(
        "ix_external_workout_dedup",
        "external_workout",
        ["user_id", "source", "external_id"],
        unique=True,
    )
    op.create_index(
        "ix_external_workout_user_started",
        "external_workout",
        ["user_id", "started_at"],
    )


def downgrade():
    op.drop_index("ix_external_workout_user_started", table_name="external_workout")
    op.drop_index("ix_external_workout_dedup", table_name="external_workout")
    op.drop_table("external_workout")
