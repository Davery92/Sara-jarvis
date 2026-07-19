"""Interoception / self-diagnostics — task_failure ledger + system_event ring buffer.

Phase 2 of SARA_AUDIT_AND_FIX_PLAN. Two tables so Sara can feel her own body:

- task_failure: one row per (task_name, error_class); upserted on every Celery
  FAILURE with first_seen/last_seen/occurrences. Read at deliberation time to
  inject a health digest and to answer "what's broken?".
- system_event: a queryable ring buffer of WARNING+ log records + task failures +
  deploy/interoception events, each with a stable event_id. ~30-day retention.

Both use timestamptz columns (aware UTC) — the new convention, avoiding the
naive-datetime trap that Phase 1 cleaned up.

Revision ID: 101_interoception_diagnostics
Revises: 100_fleet_agent
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "101_interoception_diagnostics"
down_revision = "100_fleet_agent"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "task_failure" not in tables:
        op.create_table(
            "task_failure",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("task_name", sa.String(255), nullable=False),
            sa.Column("error_class", sa.String(255), nullable=False),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("traceback", sa.Text, nullable=True),
            sa.Column("event_id", sa.String(64), nullable=True),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
            sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
            sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("task_name", "error_class", name="uq_task_failure_task_error"),
        )
        op.create_index("ix_task_failure_last_seen", "task_failure", ["last_seen"])
        op.create_index("ix_task_failure_task_name", "task_failure", ["task_name"])

    if "system_event" not in tables:
        op.create_table(
            "system_event",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("category", sa.String(32), nullable=False, server_default="log"),
            sa.Column("service", sa.String(128), nullable=True),
            sa.Column("level", sa.String(16), nullable=True),
            sa.Column("logger", sa.String(255), nullable=True),
            sa.Column("message", sa.Text, nullable=True),
            sa.Column("traceback", sa.Text, nullable=True),
            sa.Column("meta", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_system_event_created_at", "system_event", ["created_at"])
        op.create_index("ix_system_event_category", "system_event", ["category"])
        op.create_index("ix_system_event_event_id", "system_event", ["event_id"])
        op.create_index("ix_system_event_level", "system_event", ["level"])


def downgrade():
    op.drop_table("system_event")
    op.drop_table("task_failure")
