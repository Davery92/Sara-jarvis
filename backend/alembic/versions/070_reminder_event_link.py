"""Link reminders to calendar events + daily top-up scheduled job.

Revision ID: 070_reminder_event_link
Revises: 069_narrator_scheduled
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "070_reminder_event_link"
down_revision = "069_narrator_scheduled"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("reminder")}

    if "event_id" not in cols:
        op.add_column(
            "reminder",
            sa.Column("event_id", sa.String(), nullable=True),
        )
        op.create_foreign_key(
            "fk_reminder_event_id",
            "reminder",
            "calendar_event",
            ["event_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_reminder_event_id",
            "reminder",
            ["event_id"],
        )

    # Daily top-up job for recurring calendar event reminders
    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'calendar-reminder-topup',
                'Calendar Reminder Top-up',
                'Daily task that extends reminders for recurring calendar events past the initial 30-day window.',
                'notifications',
                'app.tasks.inproc_schedulers.calendar_reminder_topup',
                'cron', '5 3 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM scheduled_job WHERE key = 'calendar-reminder-topup'")
    )
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("reminder")}
    if "event_id" in cols:
        op.drop_index("ix_reminder_event_id", table_name="reminder")
        op.drop_constraint("fk_reminder_event_id", "reminder", type_="foreignkey")
        op.drop_column("reminder", "event_id")
