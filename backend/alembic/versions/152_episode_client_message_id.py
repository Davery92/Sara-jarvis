"""Idempotent chat episode writes — harness rebuild Phase 7.

`store_conversation` deduplicated episodes by ORDINAL: count what is already in
the DB for this conversation, skip that many entries of the incoming message
list, store the rest. That is only correct if turns are strictly serialized.
On 2026-09-11 turn 4 ran as a zombie for 500 seconds and stored mid-flight,
which shifted the count under the turns that followed — two of David's six
messages never became episodes at all, and the same skew is what makes every
conversation double-store assistant reply #1 at turn 2
(gotcha_episode_ordinal_dup_store).

A client-supplied id makes the write idempotent by identity instead of by
position: the same message stored twice is one row, two overlapping turns are
two rows, and a turn that is cancelled before the model answers still has its
user episode. `reply_to_client_message_id` ties the assistant episode to the
user turn it answers, which no ordinal ever really did.

Revision ID: 152_episode_client_message_id
Revises: 151_correction
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa

revision = "152_episode_client_message_id"
down_revision = "151_correction"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE episode ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(64)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE episode ADD COLUMN IF NOT EXISTS reply_to_client_message_id VARCHAR(64)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE conversation_turn ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(64)"
    ))
    # Partial, so the millions of pre-existing NULL rows do not collide with
    # each other. (conversation_id, role, client_message_id) rather than the id
    # alone: the user turn and the assistant reply are separate rows, and a
    # client that reuses an id across conversations is a client bug we survive.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_episode_client_message_id
        ON episode (conversation_id, role, client_message_id)
        WHERE client_message_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_conversation_turn_client_message_id
        ON conversation_turn (conversation_id, role, client_message_id)
        WHERE client_message_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_episode_reply_to_client_message_id
        ON episode (reply_to_client_message_id)
        WHERE reply_to_client_message_id IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_episode_reply_to_client_message_id"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_conversation_turn_client_message_id"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_episode_client_message_id"))
    bind.execute(sa.text("ALTER TABLE conversation_turn DROP COLUMN IF EXISTS client_message_id"))
    bind.execute(sa.text("ALTER TABLE episode DROP COLUMN IF EXISTS reply_to_client_message_id"))
    bind.execute(sa.text("ALTER TABLE episode DROP COLUMN IF EXISTS client_message_id"))
