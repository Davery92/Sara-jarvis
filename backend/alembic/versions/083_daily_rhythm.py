"""Daily Rhythm Engine: persistent model of David's typical day.

Adds the `daily_rhythm` table (one row per user_id/rhythm_key/day_scope —
wake, bedtime, leave_home, gym_window, etc, all ET local times) and
registers the nightly recompute job at 3:45 AM ET, after place-discovery
(3:30) and before attention-learn cleanup windows.

Revision ID: 083_daily_rhythm
Revises: 082_disable_legacy_weekly_digest
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "083_daily_rhythm"
down_revision = "082_disable_legacy_weekly_digest"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "daily_rhythm" not in insp.get_table_names():
        op.create_table(
            "daily_rhythm",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rhythm_key", sa.String(50), nullable=False),
            sa.Column("day_scope", sa.String(10), nullable=False, server_default="weekday"),
            sa.Column("window_start", sa.Time(), nullable=True),
            sa.Column("window_end", sa.Time(), nullable=True),
            sa.Column("median_time", sa.Time(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("variance_minutes", sa.Integer(), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "rhythm_key", "day_scope", name="uq_daily_rhythm_user_key_scope"),
        )
        op.create_index("ix_daily_rhythm_user_id", "daily_rhythm", ["user_id"])

    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'recompute-daily-rhythm',
                'Recompute Daily Rhythm',
                'Nightly percentile pass over location, workout, food, calendar, and behavioral-pattern history to re-derive wake/sleep/gym/meal/work windows — David''s learned daily rhythm.',
                'learning',
                'app.tasks.daily_rhythm.recompute_daily_rhythm',
                'cron', '45 3 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 1800,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'recompute-daily-rhythm'"))
    op.drop_index("ix_daily_rhythm_user_id", table_name="daily_rhythm")
    op.drop_table("daily_rhythm")
