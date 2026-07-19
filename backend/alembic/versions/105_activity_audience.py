"""Feed hygiene — tag sara_activity_log entries internal vs user_facing (Phase 6).

"While you were away" should render only what Sara did *for David*, not her own
goal-lifecycle / loop-management / habituation chatter (the JIT-goal-funeral
saga). An `audience` column makes the feed filterable; a dedup_key collapses
near-identical repeats.

Revision ID: 105_activity_audience
Revises: 104_eval_beat
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "105_activity_audience"
down_revision = "104_eval_beat"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "sara_activity_log" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sara_activity_log")}
    if "audience" not in cols:
        op.add_column("sara_activity_log",
                      sa.Column("audience", sa.String(16), nullable=True))
        op.create_index("ix_sara_activity_audience", "sara_activity_log", ["audience"])
    if "dedup_key" not in cols:
        op.add_column("sara_activity_log",
                      sa.Column("dedup_key", sa.String(200), nullable=True))
        op.create_index("ix_sara_activity_dedup", "sara_activity_log", ["dedup_key"])


def downgrade():
    op.drop_index("ix_sara_activity_dedup", table_name="sara_activity_log")
    op.drop_index("ix_sara_activity_audience", table_name="sara_activity_log")
    op.drop_column("sara_activity_log", "dedup_key")
    op.drop_column("sara_activity_log", "audience")
