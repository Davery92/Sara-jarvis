"""ACS world-delta watermark — Brain Alignment ACS1.

The daemon is event-driven, not polling: on each think it asks the backend
"what changed while I was idle" and the backend returns a world_delta since the
last time it served one. This column is that watermark.

Revision ID: 099_acs_world_delta
Revises: 098_soul_proposal_source
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "099_acs_world_delta"
down_revision = "098_soul_proposal_source"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "sara_daemon_state" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("sara_daemon_state")}
        if "last_delta_served_at" not in cols:
            op.add_column("sara_daemon_state",
                          sa.Column("last_delta_served_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    try:
        op.drop_column("sara_daemon_state", "last_delta_served_at")
    except Exception:
        pass
