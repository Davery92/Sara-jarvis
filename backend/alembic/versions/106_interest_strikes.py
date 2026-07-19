"""Interest feedback signal — strike counter for two-strikes auto-mute (Phase 6.3).

David's reactions (dismiss / ignore / negative sentiment) decrement an interest's
weight and add a strike; two strikes auto-mutes it via the existing `blocked`
flag (never delete — reflection re-creates deletions). Rage-typed all-caps should
never be the *first* signal that lands.

Revision ID: 106_interest_strikes
Revises: 105_activity_audience
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "106_interest_strikes"
down_revision = "105_activity_audience"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "sara_interest" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sara_interest")}
    if "strikes" not in cols:
        op.add_column("sara_interest",
                      sa.Column("strikes", sa.Integer, nullable=False, server_default="0"))
    if "last_reaction_at" not in cols:
        op.add_column("sara_interest",
                      sa.Column("last_reaction_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("sara_interest", "last_reaction_at")
    op.drop_column("sara_interest", "strikes")
