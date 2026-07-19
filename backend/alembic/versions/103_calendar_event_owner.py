"""Store calendar-event ownership at sync time (Phase 3).

Adds `owner` (self | <family member> | family | unknown) and `owner_relation`
to calendar_event so every consumer — including raw SQL in day-replay, monitors,
and the PKG — gets ownership for free instead of re-deriving it (or not).

Revision ID: 103_calendar_event_owner
Revises: 102_interoception_beats
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "103_calendar_event_owner"
down_revision = "102_interoception_beats"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "calendar_event" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("calendar_event")}
    if "owner" not in cols:
        op.add_column("calendar_event", sa.Column("owner", sa.String(64), nullable=True))
    if "owner_relation" not in cols:
        op.add_column("calendar_event", sa.Column("owner_relation", sa.String(32), nullable=True))
    op.create_index("ix_calendar_event_owner", "calendar_event", ["owner"])


def downgrade():
    op.drop_index("ix_calendar_event_owner", table_name="calendar_event")
    op.drop_column("calendar_event", "owner_relation")
    op.drop_column("calendar_event", "owner")
