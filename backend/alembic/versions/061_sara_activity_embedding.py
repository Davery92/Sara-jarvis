"""Sara activity-log embedding column — Phase 5 of the ACS redo (recall before research).

Revision ID: 061_sara_activity_embedding
Revises: 060_sara_inbox
Create Date: 2026-05-06

Adds a 1024-dim pgvector column to sara_activity_log so the daemon can find
its own prior thoughts via similarity search before diving into a topic. Uses
the same bge-m3 embedding pipeline as the rest of the system.

Index choice: HNSW with cosine ops. Each daemon think turn does one similarity
query; the table will stay small (thousands not millions of rows over years
of operation), so HNSW is fine and faster to query than IVFFlat at this scale.
"""
from alembic import op
import sqlalchemy as sa


revision = "061_sara_activity_embedding"
down_revision = "060_sara_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sara_activity_log ADD COLUMN embedding vector(1024)")
    op.execute(
        "CREATE INDEX ix_sara_activity_log_embedding "
        "ON sara_activity_log USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sara_activity_log_embedding")
    op.execute("ALTER TABLE sara_activity_log DROP COLUMN IF EXISTS embedding")
