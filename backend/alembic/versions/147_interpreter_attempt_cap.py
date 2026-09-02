"""Bound the world interpreter's retries.

A model response the interpreter can't parse used to leave the event at
interpreter_status='retry' forever, and drain_interpretations re-dispatched it
every cycle — one LLM call per cycle, indefinitely. `attempt_count` belongs to
the deterministic reducer, so the interpreter needs its own counter to stop at.

Revision ID: 147_interpreter_attempt_cap
Revises: 146_world_attention_cognition
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa

revision = "147_interpreter_attempt_cap"
down_revision = "146_world_attention_cognition"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        ALTER TABLE world_event_processing
        ADD COLUMN IF NOT EXISTS interpreter_attempt_count INTEGER NOT NULL DEFAULT 0
    """))
    # Events already parked in 'retry' carry no attempt history; start them at
    # zero so the cap gives each one a fair set of tries under the new rule.
    op.get_bind().execute(sa.text("""
        UPDATE world_event_processing
        SET interpreter_attempt_count = 0
        WHERE interpreter_status IN ('pending', 'retry')
    """))


def downgrade():
    op.get_bind().execute(sa.text("""
        ALTER TABLE world_event_processing DROP COLUMN IF EXISTS interpreter_attempt_count
    """))
    op.get_bind().execute(sa.text("""
        UPDATE world_event_processing SET interpreter_status = 'retry'
        WHERE interpreter_status = 'failed'
    """))
