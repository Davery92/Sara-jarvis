"""Cross-device (Apple Watch + iPhone) workout sync.

SARA_APPLE_WATCH_FITNESS_IMPLEMENTATION_PLAN_2026_07_25 §6.1-§6.4, §6.9.

Today `active_workout_session` assumes exactly one controller: the phone posts
a mutation, the row changes, done. Once the Watch can also issue Start and Log
Set, three things break:

  1. Two devices can race the same mutation, and a retried `Log Set` over a
     flaky link silently writes a second `workout_log` row.
  2. Start implicitly abandons whatever was active — fine when only one device
     could ask, catastrophic when the Watch asks while the phone is mid-set.
  3. The completed HealthKit workout is matched back to the Sara session by a
     same-day strength heuristic, which cannot tell "the workout Sara owns"
     from "a walk David took an hour earlier".

This migration adds the durable spine for all three: a monotonic session
`version` for optimistic concurrency, a command log keyed by client-generated
`command_id` for idempotent replay, an explicit HealthKit workout link, an
approval-gated proposal table, and the bounded-policy record that lets Sara
act inside limits David already agreed to (§6.9).

Nothing here changes behaviour on its own — the v2 command service reads these
and stays behind WORKOUT_COMMAND_V2_ENABLED.

Revision ID: 124_watch_workout_sync
Revises: 123_interest_lifecycle
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "124_watch_workout_sync"
down_revision = "123_interest_lifecycle"
branch_labels = None
depends_on = None


PROPOSAL_STATUSES = ("pending", "approved", "rejected", "expired", "superseded")
COMMAND_STATUSES = ("applied", "replayed", "conflict", "rejected")


def _cols(insp, table):
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # ── §6.1 session versioning + device identity ────────────────────────
    if "active_workout_session" in tables:
        cols = _cols(insp, "active_workout_session")
        add = [
            # Monotonic. Every accepted mutation bumps it; a command carrying a
            # stale expected_version is a conflict, not a silent overwrite.
            ("version", sa.Column("version", sa.BigInteger(), nullable=False, server_default="1")),
            ("origin_device", sa.Column("origin_device", sa.String(20), nullable=True)),
            # Idempotency key for Start itself: a retried start from the same
            # attempt replays instead of creating a second session.
            ("start_attempt_id", sa.Column("start_attempt_id", sa.String(64), nullable=True)),
            ("healthkit_state", sa.Column("healthkit_state", sa.String(20), nullable=True)),
            ("healthkit_workout_uuid", sa.Column("healthkit_workout_uuid", sa.String(128), nullable=True)),
            ("healthkit_activity_type", sa.Column("healthkit_activity_type", sa.String(80), nullable=True)),
            ("healthkit_started_at", sa.Column("healthkit_started_at", sa.DateTime(timezone=True), nullable=True)),
            ("healthkit_ended_at", sa.Column("healthkit_ended_at", sa.DateTime(timezone=True), nullable=True)),
            ("last_device_sync_at", sa.Column("last_device_sync_at", sa.DateTime(timezone=True), nullable=True)),
        ]
        for name, col in add:
            if name not in cols:
                op.add_column("active_workout_session", col)

        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_aws_start_attempt
            ON active_workout_session(user_id, start_attempt_id)
            WHERE start_attempt_id IS NOT NULL
        """)
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_aws_healthkit_uuid
            ON active_workout_session(user_id, healthkit_workout_uuid)
            WHERE healthkit_workout_uuid IS NOT NULL
        """)

    # ── §6.2 durable command idempotency ─────────────────────────────────
    if "workout_session_command" not in tables:
        op.create_table(
            "workout_session_command",
            # Client-generated before sending, so a command that times out
            # in-flight can be retried byte-identically and replay.
            sa.Column("command_id", sa.String(64), primary_key=True),
            sa.Column("session_id", sa.String(36), nullable=True, index=True),
            sa.Column("user_id", sa.String(36), nullable=False, index=True),
            sa.Column("origin_device", sa.String(20), nullable=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("expected_version", sa.BigInteger(), nullable=True),
            sa.Column("payload", JSONB, nullable=True),
            # The exact response the first application produced. A replay
            # returns this verbatim so both devices converge on one answer.
            sa.Column("result", JSONB, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="applied"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_wsc_session_created", "workout_session_command", ["session_id", "created_at"]
        )

    # ── §6.2 second line of defence on set rows ──────────────────────────
    # Even if the command log were bypassed, one command_id can back at most
    # one workout_log row.
    if "workout_log" in tables and "command_id" not in _cols(insp, "workout_log"):
        op.add_column("workout_log", sa.Column("command_id", sa.String(64), nullable=True))
        op.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_workout_log_command
            ON workout_log(command_id) WHERE command_id IS NOT NULL
        """)

    # ── §6.7 coaching as an ordered event, not a blocking return value ───
    if "workout_session_event" not in tables:
        op.create_table(
            "workout_session_event",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("session_id", sa.String(36), nullable=False, index=True),
            sa.Column("user_id", sa.String(36), nullable=False, index=True),
            # Version the event describes — lets a device drop coaching that
            # newer sets have already made stale.
            sa.Column("after_version", sa.BigInteger(), nullable=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("speak", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
            sa.Column("proposal_id", sa.String(36), nullable=True),
            sa.Column("payload", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_wse_session_version", "workout_session_event", ["session_id", "after_version"]
        )

    # ── §6.3 proposals: calculated ≠ applied ─────────────────────────────
    if "workout_adjustment_proposal" not in tables:
        op.create_table(
            "workout_adjustment_proposal",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False, index=True),
            # Nullable: post-workout progression proposals outlive the session
            # they were derived from (§6.8) and are approved outside the gym.
            sa.Column("session_id", sa.String(36), nullable=True, index=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("scope", JSONB, nullable=True),
            sa.Column("current_value", JSONB, nullable=True),
            sa.Column("proposed_value", JSONB, nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("evidence", JSONB, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by_device", sa.String(20), nullable=True),
            sa.Column("approval_command_id", sa.String(64), nullable=True),
        )
        op.create_index(
            "ix_wap_user_status", "workout_adjustment_proposal", ["user_id", "status"]
        )

    # ── §6.9 standing bounded policies ───────────────────────────────────
    # One row per user. Sara may act inside these without re-asking; widening
    # them is itself a change requiring approval, hence approved_at/by.
    if "workout_approved_policy" not in tables:
        op.create_table(
            "workout_approved_policy",
            sa.Column("user_id", sa.String(36), primary_key=True),
            sa.Column("policy", JSONB, nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
            sa.Column("approved_by_device", sa.String(20), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        )

    # ── §6.4 exact HealthKit link ────────────────────────────────────────
    if "external_workout" in tables and "sara_session_id" not in _cols(insp, "external_workout"):
        op.add_column("external_workout", sa.Column("sara_session_id", sa.String(36), nullable=True))
        op.create_index(
            "ix_external_workout_sara_session", "external_workout", ["user_id", "sara_session_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "external_workout" in tables and "sara_session_id" in _cols(insp, "external_workout"):
        op.execute("DROP INDEX IF EXISTS ix_external_workout_sara_session")
        op.drop_column("external_workout", "sara_session_id")

    for t in (
        "workout_approved_policy",
        "workout_adjustment_proposal",
        "workout_session_event",
        "workout_session_command",
    ):
        if t in tables:
            op.drop_table(t)

    if "workout_log" in tables and "command_id" in _cols(insp, "workout_log"):
        op.execute("DROP INDEX IF EXISTS ix_workout_log_command")
        op.drop_column("workout_log", "command_id")

    if "active_workout_session" in tables:
        cols = _cols(insp, "active_workout_session")
        op.execute("DROP INDEX IF EXISTS ix_aws_start_attempt")
        op.execute("DROP INDEX IF EXISTS ix_aws_healthkit_uuid")
        for name in (
            "last_device_sync_at", "healthkit_ended_at", "healthkit_started_at",
            "healthkit_activity_type", "healthkit_workout_uuid", "healthkit_state",
            "start_attempt_id", "origin_device", "version",
        ):
            if name in cols:
                op.drop_column("active_workout_session", name)
