"""Drop the legacy attention/inbox tables (SARA_ALIVE item 1.1, 2026-07-30).

outbox_item has been the sole live read/write target since the Phase G
migration (131_outbox_item.py / af5d4d9e). Zero backend/app, acs-daemon, or
acs-tool-runner code references autonomy_attention_item or jarvis_inbox
anymore; autonomy_attention_item's last row predates the outbox cutover
commit, and jarvis_inbox's last row is from 2025-12-26 — neither has taken
a live write since. Usage gate (outbox_usage_log) closed at 92 reads / 47
writes with badge parity holding on every read before this migration was
authored. A pre-drop pg_dump of both tables is kept locally (gitignored,
backend/backups/) and was verified to list both tables' schema, data,
indexes, and the sync trigger.

Revision ID: 135_drop_legacy_attention_tables
Revises: 134_singular_context_turn_log
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "135_drop_legacy_attention_tables"
down_revision = "134_singular_context_turn_log"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "DROP TRIGGER IF EXISTS trg_sync_attention_to_outbox ON autonomy_attention_item"
    ))
    bind.execute(sa.text("DROP TABLE IF EXISTS autonomy_attention_item"))
    bind.execute(sa.text("DROP TABLE IF EXISTS jarvis_inbox"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS sync_attention_to_outbox()"))


def downgrade():
    raise NotImplementedError(
        "Restore autonomy_attention_item/jarvis_inbox from the pre-drop pg_dump "
        "(backend/backups/outbox_predrop_20260730_201023.dump), not a schema replay."
    )
