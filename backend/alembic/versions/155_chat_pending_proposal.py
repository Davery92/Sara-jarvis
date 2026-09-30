"""chat_pending_proposal — Sara repair plan R01 review remediation
2026-09-25, extended 2026-09-26 with `presented_summary`.

A typed pending-proposal record for the chat mutation gate, distinct from
`_CHAT_INVOKED_MUTATING_TOOL_NAMES` (which only remembers a bare tool NAME
that already EXECUTED, conflating "already done" with "awaiting approval").
See app/models/chat_pending_proposal.py's module docstring for the full
rationale and its relationship to the existing
workout_adjustment_proposal/soul_change_proposals/prompt_proposals pattern.

`presented_summary` (added 2026-09-26, in this same not-yet-applied
migration rather than a new one — this revision has never been applied to
any database, so there is no deployed schema to migrate forward from):
Sara's own final reply text for the turn a proposal was created on — the
actual evidence the user was told about it, not just that a tool call was
internally attempted. See chat_proposal_service.py.

NOT APPLIED to any running database as part of this repair session — see
the repair status document for the deployment boundary. Self-provisioned
directly in tests via Base.metadata.create_all, matching this codebase's
existing convention for in-flight schema additions.

Revision ID: 155_chat_pending_proposal
Revises: 154_saved_meal
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

revision = "155_chat_pending_proposal"
down_revision = "154_saved_meal"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS chat_pending_proposal (
            id              VARCHAR(36) PRIMARY KEY,
            user_id         VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            conversation_id VARCHAR(64) NOT NULL,
            tool_name       VARCHAR(120) NOT NULL,
            arguments_json  TEXT NOT NULL,
            summary         TEXT,
            source_message  TEXT,
            presented_summary TEXT,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at      TIMESTAMPTZ NOT NULL,
            consumed_at     TIMESTAMPTZ
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_chat_pending_proposal_lookup
        ON chat_pending_proposal (user_id, conversation_id, tool_name, status)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_chat_pending_proposal_lookup"))
    bind.execute(sa.text("DROP TABLE IF EXISTS chat_pending_proposal"))
