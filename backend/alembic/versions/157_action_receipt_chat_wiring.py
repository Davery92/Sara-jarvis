"""R03 (Sara repair plan 2026-09-25): wire action_receipt into the general
chat tool-calling loop, not just standing-order execution.

`action_receipt` already exists (migrations/add_action_receipt_table.py,
alembic 121/137) but is only ever written by
`action_receipt_service.record_standing_order_action` — every OTHER
mutating tool a chat turn actually executes leaves no durable record at
all, which is the root of "false reminder/research/chess/goal success":
nothing exists to check a later confirmation or challenge against.

Two additive changes, both backward compatible with existing rows (NULL
default, no data touched):

- `conversation_id` — lets a later turn (same conversation), after
  compaction, or from a different client retrieve "what did Sara actually
  do in this conversation" without relying on chat history text.
- A partial unique index on `idempotency_key` (WHERE NOT NULL) — the chat
  wiring uses the tool_call's own id as its idempotency key, so a
  duplicated delivery of the same call (a retried SSE frame, a reconnect)
  writes at most one receipt via `ON CONFLICT ... DO NOTHING`, not a
  read-then-write race. Existing standing-order rows keep their
  timestamp-based keys, which happen to already be unique in practice but
  were never enforced — the partial index does not touch any existing row
  (WHERE idempotency_key IS NOT NULL matches everything with a key, but
  DO NOTHING on the rare true collision is the correct behavior for that
  path too: the same standing-order action retried should not double-
  record).

NOT applied to any running database as part of this repair session — see
the repair status document for the deployment boundary. Self-provisioned
directly in tests via raw SQL against the disposable Postgres, matching
this codebase's existing convention for in-flight schema additions.

Revision ID: 157_action_receipt_chat_wiring
Revises: 156_revoked_token
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "157_action_receipt_chat_wiring"
down_revision = "156_revoked_token"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        ALTER TABLE action_receipt
        ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(64)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_action_receipt_conversation
        ON action_receipt (conversation_id, created_at DESC)
        WHERE conversation_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_action_receipt_idempotency_key
        ON action_receipt (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS uq_action_receipt_idempotency_key"))
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_action_receipt_conversation"))
    bind.execute(sa.text("ALTER TABLE action_receipt DROP COLUMN IF EXISTS conversation_id"))
