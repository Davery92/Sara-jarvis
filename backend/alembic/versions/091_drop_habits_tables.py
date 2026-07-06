"""Drop the Habits vertical — SARA_UNLEASHED Phase U.3.

R18: 6 tables, 5 UI components, 2 docs — a fully-built, never-used vertical.
Audited before dropping (2026-07-06): `habits` and `habit_items` are truly
empty; `habit_logs` (2 rows), `habit_instances` (3 rows), `habit_streaks`
(1 row) hold a single abandoned test habit from 2025-08-21/22 with no
activity since — not live data. The modern machinery (commitments +
standing orders + patterns) already models what habits promised; a habit is
a recurring commitment with a streak.

Fully reversible: downgrade() recreates the exact schema (captured live via
`\\d` against production before dropping) — but does NOT restore the 6 rows
of abandoned test data, since this is a structural revert, not a data
restore.

Revision ID: 091_drop_habits_tables
Revises: 090_deep_deliberation
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "091_drop_habits_tables"
down_revision = "090_deep_deliberation"
branch_labels = None
depends_on = None

_DROP_ORDER = [
    "habit_streaks", "habit_links", "habit_items",
    "habit_instances", "habit_logs", "habits",
]


def upgrade():
    for table in _DROP_ORDER:
        op.drop_table(table)


def downgrade():
    op.create_table(
        "habits",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("target_numeric", sa.Float()),
        sa.Column("unit", sa.Text()),
        sa.Column("rrule", sa.Text(), nullable=False),
        sa.Column("weekly_minimum", sa.Integer()),
        sa.Column("monthly_minimum", sa.Integer()),
        sa.Column("windows", sa.Text()),
        sa.Column("checklist_mode", sa.String()),
        sa.Column("checklist_threshold", sa.Float()),
        sa.Column("grace_days", sa.Integer()),
        sa.Column("retro_hours", sa.Integer()),
        sa.Column("paused", sa.Integer()),
        sa.Column("pause_from", sa.DateTime()),
        sa.Column("pause_to", sa.DateTime()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("current_streak", sa.Integer(), nullable=False),
        sa.Column("best_streak", sa.Integer(), nullable=False),
        sa.Column("last_completed", sa.DateTime()),
        sa.Column("vacation_from", sa.DateTime()),
        sa.Column("vacation_to", sa.DateTime()),
    )
    op.create_table(
        "habit_logs",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("habit_id", sa.String(), nullable=False),
        sa.Column("instance_id", sa.String()),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("payload", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "habit_instances",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("habit_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("window", sa.Text()),
        sa.Column("expected", sa.Integer()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress", sa.Float()),
        sa.Column("total_amount", sa.Float()),
        sa.Column("target", sa.Float()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "habit_items",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("habit_id", sa.String(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "habit_links",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("habit_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("meta", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "habit_streaks",
        sa.Column("habit_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("current_streak", sa.Integer()),
        sa.Column("best_streak", sa.Integer()),
        sa.Column("last_completed", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )
