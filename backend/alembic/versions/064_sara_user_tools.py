"""Sara user-defined tools — Phase 8 of the ACS redo (self-tooling).

Revision ID: 064_sara_user_tools
Revises: 063_sara_interest
Create Date: 2026-05-07

Three tables in a separate namespace from the hardcoded `acs_daemon_tools.py`
surface. Hardcoded tools stay code (immutable). Her tools are data, executed
in a separate sandbox process (acs-tool-runner — separate deploy).

  sara_tool             — definition (name, schema, current pointer, kill switch)
  sara_tool_version     — append-only history of code revisions
  sara_tool_invocation  — audit log of every call, with args/result/duration

Approval flow: new tool starts enabled=FALSE; David flips it on after seeing
the code in the ACSPage review queue. Version updates do not auto-activate —
the daemon must explicitly call /activate?version=N.
"""
from alembic import op
import sqlalchemy as sa


revision = "064_sara_user_tools"
down_revision = "063_sara_interest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sara_tool",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("args_schema", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("active_version_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "name ~ '^[a-z][a-z0-9_]{2,63}$'",
            name="sara_tool_name_format",
        ),
    )

    op.create_table(
        "sara_tool_version",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tool_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sara_tool.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tool_id", "version", name="sara_tool_version_unique"),
    )
    op.execute(
        "CREATE INDEX ix_sara_tool_version_tool "
        "ON sara_tool_version (tool_id, version DESC)"
    )

    # Add the FK from sara_tool.active_version_id → sara_tool_version.id
    # after both tables exist (chicken-and-egg avoided).
    op.create_foreign_key(
        "sara_tool_active_version_fk",
        source_table="sara_tool",
        referent_table="sara_tool_version",
        local_cols=["active_version_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "sara_tool_invocation",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tool_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sara_tool.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sara_tool_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("args", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_sara_tool_invocation_tool "
        "ON sara_tool_invocation (tool_id, started_at DESC)"
    )


def downgrade() -> None:
    op.drop_table("sara_tool_invocation")
    op.drop_constraint("sara_tool_active_version_fk", "sara_tool", type_="foreignkey")
    op.execute("DROP INDEX IF EXISTS ix_sara_tool_version_tool")
    op.drop_table("sara_tool_version")
    op.drop_table("sara_tool")
