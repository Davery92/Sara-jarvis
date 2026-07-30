"""Real turn counter for the legacy 19-source context fallback deletion gate.

David's own bar (work-order 2026-07-30): delete the legacy assembly once
SINGULAR_CONTEXT has >=200 clean real turns logged (count, not days).
"Clean" = the new kernel-only assembly actually rendered and replaced the
legacy one for that turn (main_simple.py's `_new_rendered and
_context_cutover_live` branch). This table lets that be measured honestly
as real chat turns happen — see app/services/context_diet_usage.py — not
manufactured via replayed conversations, which would defeat the point of
requiring a count in the first place.

Revision ID: 134_singular_context_turn_log
Revises: 133_outbox_usage_log
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "134_singular_context_turn_log"
down_revision = "133_outbox_usage_log"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS singular_context_turn_log (
            id          BIGSERIAL PRIMARY KEY,
            user_id     VARCHAR(255) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_singular_context_turn_log_created
        ON singular_context_turn_log (created_at DESC)
    """))


def downgrade():
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS singular_context_turn_log"))
