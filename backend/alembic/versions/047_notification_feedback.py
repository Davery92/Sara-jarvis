"""Add feedback fields to notification_log for engagement tracking

Revision ID: 047_notification_feedback
Revises: 046_notification_preferences
Create Date: 2026-02-20

Adds:
- read_at: When the user saw/opened the notification
- engaged: Whether the user actively engaged (clicked, replied, etc.)
- dismissed_at: When the user explicitly dismissed the notification
- response_text: Any text the user typed in reply
"""
from alembic import op


revision = "047_notification_feedback"
down_revision = "046_notification_preferences"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;
    """)
    op.execute("""
        ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS engaged BOOLEAN DEFAULT FALSE;
    """)
    op.execute("""
        ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ;
    """)
    op.execute("""
        ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS response_text TEXT;
    """)

    # Index for engagement analysis queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_notification_log_feedback
        ON notification_log (user_id, category, sent_at)
        WHERE sent = TRUE;
    """)


def downgrade():
    op.execute("ALTER TABLE notification_log DROP COLUMN IF EXISTS read_at;")
    op.execute("ALTER TABLE notification_log DROP COLUMN IF EXISTS engaged;")
    op.execute("ALTER TABLE notification_log DROP COLUMN IF EXISTS dismissed_at;")
    op.execute("ALTER TABLE notification_log DROP COLUMN IF EXISTS response_text;")
    op.execute("DROP INDEX IF EXISTS ix_notification_log_feedback;")
