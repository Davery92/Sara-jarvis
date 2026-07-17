"""notification_log blocked_count — SARA_UNLEASHED Phase A.4

Dedup-blocked sends used to insert a fresh notification_log row every time
(106/week of pure churn per the plan's baseline). This adds a counter column
so a blocked attempt increments the existing row instead of creating a new
one.

Revision ID: 088_notification_blocked_count
Revises: 087_ml_feature_store
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "088_notification_blocked_count"
down_revision = "087_ml_feature_store"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_log",
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("notification_log", "blocked_count")
