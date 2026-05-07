"""Sara activity log + focus — Phase 2 of the ACS redo (ambient self-context).

Revision ID: 059_sara_activity_log_focus
Revises: 058_acs_daemon_state
Create Date: 2026-05-06

Two tables that give the daemon a self that persists across ticks:

- sara_activity_log: append-only stream of every meaningful thing she does
  (thoughts, reflections, focus changes, boots, shutdowns). The daemon
  reads the recent tail before every think turn so the next prompt has
  ambient awareness of what she's been doing.

- sara_focus: a singleton-ish "what am I working on right now" pointer.
  Updated when she decides to pivot. The current focus is read at every
  prompt assembly. History of focus changes lives in sara_activity_log
  via kind='focus_set' / 'focus_clear' entries, so this table can stay
  small (one row).
"""
from alembic import op
import sqlalchemy as sa


revision = "059_sara_activity_log_focus"
down_revision = "058_acs_daemon_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sara_activity_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("tags", sa.dialects.postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    # Hot path: "give me the last N activity rows" — every think turn hits this.
    op.create_index(
        "ix_sara_activity_log_created_at_desc",
        "sara_activity_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_sara_activity_log_kind_created_at",
        "sara_activity_log",
        ["kind", sa.text("created_at DESC")],
    )

    op.create_table(
        "sara_focus",
        sa.Column("id", sa.String(32), primary_key=True),  # always 'singleton'
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 'singleton'", name="sara_focus_singleton"),
    )


def downgrade() -> None:
    op.drop_table("sara_focus")
    op.drop_index("ix_sara_activity_log_kind_created_at", table_name="sara_activity_log")
    op.drop_index("ix_sara_activity_log_created_at_desc", table_name="sara_activity_log")
    op.drop_table("sara_activity_log")
