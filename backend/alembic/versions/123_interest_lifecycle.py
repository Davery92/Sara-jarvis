"""Interest lifecycle status — SARA_PROACTIVENESS_IMPLEMENTATION_PLAN_2026_07_25 P5.1.

sara_interest previously had only `weight` + `blocked` — an interest was
either alive or muted, with no notion of "has David actually agreed she
should pursue this." This adds the explicit lifecycle the plan calls for:

    noticed -> candidate -> aligned -> proposed -> discussing
      -> approved | deferred | rejected -> active
      -> blocked | completed | abandoned

Existing rows (all pre-dating this concept) are backfilled to 'active' so
nothing already running silently stops — the gate this enables
(mind.py / backend_client requiring an approved-or-active interest before
provision_container/exec_in_container) is enforced going forward, not
retroactively against interests David has implicitly been fine with.

New interests created via the `add_interest` tool (source='reflection')
default to 'noticed' — she may still name and research them lightly, but
the daemon-side gate requires 'approved' or 'active' before deeper VM work.
Interests David creates himself (source='manual') default to 'approved'
since creating one is itself the approval.

Revision ID: 123_interest_lifecycle
Revises: 122_intent_graph_sync
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "123_interest_lifecycle"
down_revision = "122_intent_graph_sync"
branch_labels = None
depends_on = None

_STATUSES = (
    "noticed", "candidate", "aligned", "proposed", "discussing",
    "approved", "deferred", "rejected", "active", "blocked",
    "completed", "abandoned",
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "sara_interest" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sara_interest")}
    if "status" not in cols:
        op.add_column(
            "sara_interest",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
    op.execute(
        "ALTER TABLE sara_interest DROP CONSTRAINT IF EXISTS sara_interest_status_valid"
    )
    op.create_check_constraint(
        "sara_interest_status_valid",
        "sara_interest",
        f"status IN ({', '.join(repr(s) for s in _STATUSES)})",
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sara_interest_status ON sara_interest (status)")
    # Blocked interests should read as 'blocked' in the new lifecycle too,
    # not 'active' — keep the two flags consistent for existing rows.
    op.execute("UPDATE sara_interest SET status = 'blocked' WHERE blocked = TRUE")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sara_interest_status")
    op.execute("ALTER TABLE sara_interest DROP CONSTRAINT IF EXISTS sara_interest_status_valid")
    op.drop_column("sara_interest", "status")
