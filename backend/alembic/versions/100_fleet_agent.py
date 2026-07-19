"""Sara Fleet — health agents + read-only diagnostics (FLEET_DESIGN.md).

Extends ManagedHost with a second transport (the push agent) and adds three
tables: host_metric (numeric time-series), host_alert (edge-trigger ledger),
host_diag_command (diag queue + audit ledger).

Revision ID: 100_fleet_agent
Revises: 099_acs_world_delta
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "100_fleet_agent"
down_revision = "099_acs_world_delta"
branch_labels = None
depends_on = None


def _add_col(insp, table, col):
    cols = {c["name"] for c in insp.get_columns(table)}
    if col.name not in cols:
        op.add_column(table, col)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # --- ManagedHost: agent transport columns ------------------------------
    if "managed_host" in tables:
        _add_col(insp, "managed_host",
                 sa.Column("transport", sa.String(16), nullable=False, server_default="ssh"))
        _add_col(insp, "managed_host", sa.Column("machine_id", sa.String(64), nullable=True))
        _add_col(insp, "managed_host", sa.Column("agent_token_hash", sa.String(64), nullable=True))
        _add_col(insp, "managed_host", sa.Column("agent_version", sa.String(16), nullable=True))
        _add_col(insp, "managed_host",
                 sa.Column("agent_enrolled_at", sa.DateTime(timezone=True), nullable=True))
        _add_col(insp, "managed_host",
                 sa.Column("agent_last_report_at", sa.DateTime(timezone=True), nullable=True))
        _add_col(insp, "managed_host", sa.Column("agent_snapshot", JSONB, nullable=True))
        _add_col(insp, "managed_host", sa.Column("agent_alert_state", JSONB, nullable=True))
        existing_idx = {i["name"] for i in insp.get_indexes("managed_host")}
        if "ix_managed_host_machine_id" not in existing_idx:
            op.create_index("ix_managed_host_machine_id", "managed_host", ["machine_id"])

    # --- host_metric -------------------------------------------------------
    if "host_metric" not in tables:
        op.create_table(
            "host_metric",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("host_id", sa.String,
                      sa.ForeignKey("managed_host.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("cpu_pct", sa.Float, nullable=True),
            sa.Column("load1", sa.Float, nullable=True),
            sa.Column("mem_pct", sa.Float, nullable=True),
            sa.Column("swap_pct", sa.Float, nullable=True),
            sa.Column("disk_max_pct", sa.Float, nullable=True),
            sa.Column("temp_max_c", sa.Float, nullable=True),
            sa.Column("net_rx_bps", sa.Float, nullable=True),
            sa.Column("net_tx_bps", sa.Float, nullable=True),
            sa.Column("failed_units", sa.Integer, nullable=True),
            sa.Column("extras", JSONB, nullable=True),
        )
        op.create_index("ix_host_metric_host_id", "host_metric", ["host_id"])
        op.create_index("ix_host_metric_host_ts", "host_metric", ["host_id", "ts"])

    # --- host_alert --------------------------------------------------------
    if "host_alert" not in tables:
        op.create_table(
            "host_alert",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("host_id", sa.String,
                      sa.ForeignKey("managed_host.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rule", sa.String(48), nullable=False),
            sa.Column("severity", sa.String(16), nullable=False, server_default="normal"),
            sa.Column("state", sa.String(16), nullable=False, server_default="firing"),
            sa.Column("detail", JSONB, nullable=True),
            sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        )
        op.create_index("ix_host_alert_host_id", "host_alert", ["host_id"])
        op.create_index("ix_host_alert_rule", "host_alert", ["rule"])

    # --- host_diag_command -------------------------------------------------
    if "host_diag_command" not in tables:
        op.create_table(
            "host_diag_command",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("host_id", sa.String,
                      sa.ForeignKey("managed_host.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String, nullable=True),
            sa.Column("requested_by", sa.String(24), nullable=False, server_default="chat"),
            sa.Column("request_context", sa.String(255), nullable=True),
            sa.Column("argv", JSONB, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("denied_reason", sa.Text, nullable=True),
            sa.Column("exit_code", sa.Integer, nullable=True),
            sa.Column("stdout", sa.Text, nullable=True),
            sa.Column("stderr", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_host_diag_command_host_id", "host_diag_command", ["host_id"])
        op.create_index("ix_host_diag_command_status", "host_diag_command", ["status"])

    # --- seed beat jobs: offline sweep (5min) + metric retention (nightly) --
    if "scheduled_job" in tables:
        bind.execute(sa.text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'fleet-offline-sweep',
                'Fleet: Offline Detection Sweep',
                'Fires/resolves host_offline for agent-equipped machines that stopped reporting.',
                'health',
                'app.tasks.fleet.offline_sweep',
                'interval', NULL, 300, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'health', 280,
                TRUE, TRUE, 'system', 'system'
            ) ON CONFLICT (key) DO NOTHING
        """))
        bind.execute(sa.text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'fleet-metric-prune',
                'Fleet: Metric Retention Prune',
                'Nightly prune of host_metric rows older than 30 days.',
                'maintenance',
                'app.tasks.fleet.prune_metrics',
                'cron', '17 3 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'maintenance', 3600,
                TRUE, TRUE, 'system', 'system'
            ) ON CONFLICT (key) DO NOTHING
        """))


def downgrade():
    bind = op.get_bind()
    try:
        bind.execute(sa.text(
            "DELETE FROM scheduled_job WHERE key IN "
            "('fleet-offline-sweep', 'fleet-metric-prune') AND source = 'system'"))
    except Exception:
        pass
    for tbl in ("host_diag_command", "host_alert", "host_metric"):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
    for col in ("transport", "machine_id", "agent_token_hash", "agent_version",
                "agent_enrolled_at", "agent_last_report_at", "agent_snapshot",
                "agent_alert_state"):
        try:
            op.drop_column("managed_host", col)
        except Exception:
            pass
