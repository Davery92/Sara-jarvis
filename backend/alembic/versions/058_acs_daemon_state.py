"""ACS daemon state — singleton table for the Sara-VM-resident cognition daemon.

Revision ID: 058_acs_daemon_state
Revises: 057_health_anomaly_jobs
Create Date: 2026-05-06

Phase 1 of the ACS redo. Replaces the per-session container model with a single
long-running daemon inside the Sara VM. This table is its liveness/state record —
one row, id='singleton', upserted on every heartbeat.

Future phases will extend the daemon (ambient self-context, honest notifications,
inbox, recall-before-research). This migration is intentionally minimal.
"""
from alembic import op
import sqlalchemy as sa


revision = "058_acs_daemon_state"
down_revision = "057_health_anomaly_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sara_daemon_state",
        sa.Column("id", sa.String(32), primary_key=True),  # always 'singleton'
        sa.Column("version", sa.String(64), nullable=False, server_default="0.0.0"),
        sa.Column("state", sa.String(32), nullable=False, server_default="boot"),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("hostname", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tick_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 'singleton'", name="sara_daemon_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("sara_daemon_state")
