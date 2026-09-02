"""notification_log.suppress_reason — NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17 Phase 5.

Every code path that writes sent=false already knows why (banned_topic,
dedup, held_asleep, attention_cooldown, dedupe_key_surfaced, budget,
buzz_declined, push_failed) — it just returned that reason to a caller that
dropped it before persisting anything. Persisting it turns "a lot of
notifications are lost somewhere in the app" into a one-query diagnosis
instead of a multi-hour archaeology dig (see the double-fire investigation
this same plan grew out of).

Revision ID: 141_notify_suppress_reason
Revises: 140_notify_buzz_tunables
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa

revision = "141_notify_suppress_reason"
down_revision = "140_notify_buzz_tunables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_log",
        sa.Column("suppress_reason", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "idx_notification_log_suppress_reason",
        "notification_log",
        ["user_id", "suppress_reason", "sent_at"],
        postgresql_where=sa.text("suppress_reason IS NOT NULL"),
    )


def downgrade():
    op.drop_index("idx_notification_log_suppress_reason", table_name="notification_log")
    op.drop_column("notification_log", "suppress_reason")
