"""revoked_token — Sara repair plan R11 review remediation 2026-09-25.

Durable (Postgres) session-token revocation, replacing the first version's
Redis-only, fail-open design. See app/models/revoked_token.py's module
docstring for the full rationale.

NOT APPLIED to any running database as part of this repair session — see
the repair status document for the deployment boundary. Self-provisioned
directly in tests via Base.metadata.create_all, matching this codebase's
existing convention for in-flight schema additions.

Revision ID: 156_revoked_token
Revises: 155_chat_pending_proposal
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

revision = "156_revoked_token"
down_revision = "155_chat_pending_proposal"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS revoked_token (
            jti         VARCHAR(64) PRIMARY KEY,
            user_id     VARCHAR(36) NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            revoked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_revoked_token_expires_at ON revoked_token (expires_at)
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_revoked_token_expires_at"))
    bind.execute(sa.text("DROP TABLE IF EXISTS revoked_token"))
