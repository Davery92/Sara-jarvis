"""Drop legacy ACS tables — Phase 6 of the ACS redo (decommission).

Revision ID: 062_drop_legacy_acs_tables
Revises: 061_sara_activity_embedding
Create Date: 2026-05-06

The v1 ACS architecture (per-session containers, external auditor pushing to
David, show_david buffer with consolidation gates, interest graph, daily plan
items, directives, etc) is now fully replaced by the in-VM daemon writing to
sara_daemon_state / sara_activity_log / sara_focus / sara_inbox.

This migration:
  1. Deletes the disabled acs-* scheduled_job rows (cron entries are off, but
     they were taking up index space and showing up in the schedule list).
  2. Drops the 12 legacy ACS tables. The data has been frozen since the
     daemon switched on; there are no live writers.
"""
from alembic import op


revision = "062_drop_legacy_acs_tables"
down_revision = "061_sara_activity_embedding"
branch_labels = None
depends_on = None


LEGACY_TABLES = (
    # transcripts + audit (drop child tables before parents where possible)
    "acs_audit_dialogue",
    "acs_session_transcript",
    "acs_session_log",
    "acs_session",
    # planning surfaces
    "acs_plan_item",
    "acs_curiosity_queue",
    "acs_show_david_buffer",
    "acs_deliverable",
    "acs_directive",
    # interest graph
    "acs_interest_edge",
    "acs_interest_node",
    # self-model
    "acs_self_model",
)


def upgrade() -> None:
    # Disabled cron rows from Phase 0 stop existing entirely.
    op.execute(
        "DELETE FROM scheduled_job "
        "WHERE key LIKE 'acs-%' OR task_name LIKE 'app.tasks.acs%'"
    )
    # Drop with CASCADE to clean up any dangling FKs we missed.
    for tbl in LEGACY_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")


def downgrade() -> None:
    # Irreversible — these tables were the v1 ACS implementation, which is
    # decommissioned. There is no v1 schema to restore. If you really need
    # them back, restore from a database backup.
    raise NotImplementedError(
        "062 is irreversible; the v1 ACS schema is gone. Restore from backup."
    )
