"""Narrator: seed scheduled_job rows for daily patch notes, weekly recap, and sponsored.

Revision ID: 069_narrator_scheduled
Revises: 068_narrator_tunables
Create Date: 2026-05-17

All schedules are interpreted in America/New_York (ET) per the no-UTC rule.
"""
from alembic import op
import sqlalchemy as sa


revision = "069_narrator_scheduled"
down_revision = "068_narrator_tunables"
branch_labels = None
depends_on = None


# (key, display_name, description, task_name, schedule_kind, cron_expr, interval_seconds, visibility)
JOBS = [
    (
        "narrator-daily-patch-notes",
        "Narrator: Daily Patch Notes",
        "Fake release notes summarizing the last 24h of David's commits, PRs, "
        "errors, and workouts. Posted as a 'patch_note' severity event so it "
        "shows up on every surface.",
        "app.tasks.narrator.daily_patch_notes",
        "cron",
        "0 7 * * *",  # 7am ET daily
        None,
        "user",
    ),
    (
        "narrator-weekly-recap",
        "Narrator: Weekly Recap",
        "Same engine as daily patch notes but over the last 7 days. Posted "
        "Sunday 6pm ET — end-of-week timing on purpose.",
        "app.tasks.narrator.weekly_recap",
        "cron",
        "0 18 * * 0",  # Sunday 6pm ET
        None,
        "user",
    ),
    (
        "narrator-sponsored-interjection",
        "Narrator: Sponsored Interjection",
        "Absurdist commercial non-sequitur. The narrator interrupts itself "
        "with a fake ad. Cadence ≈ every 3 days; low priority everywhere so "
        "it never wakes the phone.",
        "app.tasks.narrator.sponsored_interjection",
        "interval",
        None,
        3 * 24 * 60 * 60,  # 3 days
        "user",
    ),
]


def upgrade():
    bind = op.get_bind()
    for (key, display, desc, task, kind, cron, interval, visibility) in JOBS:
        bind.execute(
            sa.text(
                """
                INSERT INTO scheduled_job (
                    key, display_name, description, category, task_name,
                    schedule_kind, cron_expr, interval_seconds, timezone,
                    args, kwargs, queue, expires_seconds,
                    enabled, editable, source, visibility
                ) VALUES (
                    :key, :display, :desc, 'narrator', :task,
                    :kind, :cron, :interval, 'America/New_York',
                    '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                    TRUE, TRUE, 'system', :visibility
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "display": display,
                "desc": desc,
                "task": task,
                "kind": kind,
                "cron": cron,
                "interval": interval,
                "visibility": visibility,
            },
        )


def downgrade():
    bind = op.get_bind()
    for row in JOBS:
        bind.execute(
            sa.text("DELETE FROM scheduled_job WHERE key = :key"),
            {"key": row[0]},
        )
