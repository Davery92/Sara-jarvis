"""Phase G step 7 harness — real usage-window counter.

David's own bar for step 7: "event counts, not elapsed time... never elapsed
days" — >=50 reads, >=20 writes across web + iOS, badge parity every check,
zero regressions. This table lets that be measured honestly as real traffic
happens, rather than asserted. Append-only, one row per real read/write
against outbox_item through the live app endpoints (not synthetic/replayed
traffic — see app/services/outbox_usage.py for the call sites).

Revision ID: 133_outbox_usage_log
Revises: 132_outbox_notification_fk
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "133_outbox_usage_log"
down_revision = "132_outbox_notification_fk"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS outbox_usage_log (
            id          BIGSERIAL PRIMARY KEY,
            kind        VARCHAR(10) NOT NULL CHECK (kind IN ('read', 'write')),
            surface     VARCHAR(50) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_outbox_usage_log_kind_created
        ON outbox_usage_log (kind, created_at DESC)
    """))


def downgrade():
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS outbox_usage_log"))
