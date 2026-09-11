"""Per-turn chat trace — harness rebuild Phase 9.

David had no way to see that Sara spent eight minutes calling fifteen tools.
The 2026-09-11 audit had to be reconstructed by hand from a 20-minute docker
log window, matching prompt-token lines to tool-call lines to stage timings.
This table is that reconstruction, written once per turn by the turn itself.

`ended_by` is the field that matters: a turn that ends any way other than
`model` is a turn where the harness, not Sara, decided when to stop talking.

Revision ID: 153_chat_turn_trace
Revises: 152_episode_client_message_id
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa

revision = "153_chat_turn_trace"
down_revision = "152_episode_client_message_id"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS chat_turn_trace (
            id                  BIGSERIAL PRIMARY KEY,
            user_id             VARCHAR(64),
            conversation_id     VARCHAR(64),
            client_message_id   VARCHAR(64),
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            first_token_ms      INTEGER,
            total_ms            INTEGER,
            prompt_tokens_first INTEGER,
            tool_count          INTEGER,
            rounds              INTEGER,
            -- [{name, ms, result_chars, success}]
            tools_called        JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- model | deadline | rounds | cancelled | error
            ended_by            VARCHAR(16) NOT NULL DEFAULT 'model',
            context_chars       INTEGER,
            reply_chars         INTEGER
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_chat_turn_trace_conversation
        ON chat_turn_trace (conversation_id, started_at DESC)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_chat_turn_trace_started
        ON chat_turn_trace (started_at DESC)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_chat_turn_trace_started"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_chat_turn_trace_conversation"))
    bind.execute(sa.text("DROP TABLE IF EXISTS chat_turn_trace"))
