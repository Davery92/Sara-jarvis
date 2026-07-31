"""items 5.8 + 5.9 (2026-07-31): proof-of-memory callback cards and
"Sara made you something" unwrap cards.

Both are the same shape — a rare, minted card with Sara's one-line reasoning,
shown once, dismissible — so one table serves both rather than building two
near-identical parallel systems. `kind` distinguishes them; each keeps a
loose text reference back to its source (an episode id for a memory
callback, an artifact id for an unwrap card) so "where did this come from"
is always answerable without a hard FK into either table (episode/artifacts
already have their own lifecycle; this shouldn't gate on it).

Revision ID: 138_moment_card
Revises: 137_action_receipt_undo_link
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa


revision = "138_moment_card"
down_revision = "137_action_receipt_undo_link"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS moment_card (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id VARCHAR(255) NOT NULL,
            kind VARCHAR(30) NOT NULL CHECK (kind IN ('proof_of_memory', 'artifact_unwrap')),
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            source_ref TEXT,
            source_kind VARCHAR(30),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            seen_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_moment_card_user_unseen
        ON moment_card (user_id, created_at DESC)
        WHERE seen_at IS NULL AND dismissed_at IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_moment_card_kind_created
        ON moment_card (user_id, kind, created_at DESC)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS moment_card"))
