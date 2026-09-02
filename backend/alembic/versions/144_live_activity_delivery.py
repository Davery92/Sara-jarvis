"""ActivityKit update-token registrations.

Revision ID: 144_live_activity_delivery
Revises: 143_continuous_world_model
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "144_live_activity_delivery"
down_revision = "143_continuous_world_model"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "live_activity_registration",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("activity_id", sa.String(255), nullable=False),
        sa.Column("logical_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("push_token", sa.Text(), nullable=False),
        sa.Column("device_name", sa.String(255)),
        sa.Column("environment", sa.String(16), nullable=False, server_default="production"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "activity_id", name="uq_live_activity_user_activity"),
    )
    op.create_index("ix_live_activity_user_active", "live_activity_registration", ["user_id", "is_active", "kind"])
    op.create_index("ix_live_activity_logical", "live_activity_registration", ["user_id", "logical_id", "is_active"])


def downgrade():
    op.drop_table("live_activity_registration")
