"""item 5.10 (2026-07-31): let action_receipt rows drive real Undo.

action_receipt already carries `reversible` and `undo_expires_at`, but not
which action_ledger row to actually call POST /api/system/actions/undo
against, and no way to know a receipt was already undone (so a stale
Undo button doesn't get shown/clicked twice). Both closed here so
Interior's "Recent Actions" (David's actual home surface) can wire up
the same Undo that already exists on the demoted System Dashboard,
instead of only being reachable from there.

Revision ID: 137_action_receipt_undo_link
Revises: 136_dial_learned_lock
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa


revision = "137_action_receipt_undo_link"
down_revision = "136_dial_learned_lock"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        ALTER TABLE action_receipt
        ADD COLUMN IF NOT EXISTS ledger_id INTEGER,
        ADD COLUMN IF NOT EXISTS undone BOOLEAN NOT NULL DEFAULT FALSE
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_action_receipt_ledger_id
        ON action_receipt (ledger_id) WHERE ledger_id IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_action_receipt_ledger_id"))
    bind.execute(sa.text("""
        ALTER TABLE action_receipt
        DROP COLUMN IF EXISTS ledger_id,
        DROP COLUMN IF EXISTS undone
    """))
