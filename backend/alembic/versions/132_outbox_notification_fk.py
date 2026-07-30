"""Phase G step 6 — repoint notification_log's attention-item reference.

notification_log.attention_item_id has no actual FK constraint (verified live:
only agent_run_id has one) — it's an unconstrained UUID column joined by
app code. Since outbox_item mirrors autonomy_attention_item 1:1 by id (via the
131_outbox_item dual-write trigger), a bare rename is sufficient: no data
migration needed, existing values already resolve correctly against the new
table.

Revision ID: 132_outbox_notification_fk
Revises: 131_outbox_item
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "132_outbox_notification_fk"
down_revision = "131_outbox_item"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE notification_log RENAME COLUMN attention_item_id TO outbox_item_id"
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE notification_log RENAME COLUMN outbox_item_id TO attention_item_id"
    ))
