"""Sara interest table — Phase 7 of the ACS redo (own-agency).

Revision ID: 063_sara_interest
Revises: 062_drop_legacy_acs_tables
Create Date: 2026-05-07

Persistent interests with floating weights and semantic dedup. The daemon
upserts here during reflection consolidation; idle ticks read here to seed
self-authored sara_inbox items so she pursues her interests when David's
queue is empty.

The v1 ACS had a full interest graph (acs_interest_node + acs_interest_edge,
dropped in 062). This is the v2 minimal replacement: one table, no edges.
Semantic merge via 1024-dim pgvector keeps the table clean as she reframes
the same idea in different words across reflection cycles.
"""
from alembic import op
import sqlalchemy as sa


revision = "063_sara_interest"
down_revision = "062_drop_legacy_acs_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sara_interest",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("topic", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("last_acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(32), nullable=False, server_default="reflection"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source IN ('reflection', 'external_event', 'manual')",
            name="sara_interest_source_valid",
        ),
        sa.CheckConstraint("weight >= 0.0", name="sara_interest_weight_nonneg"),
    )
    op.execute("ALTER TABLE sara_interest ADD COLUMN embedding vector(1024)")
    op.execute("CREATE INDEX ix_sara_interest_weight ON sara_interest (weight DESC)")
    op.execute(
        "CREATE INDEX ix_sara_interest_acted "
        "ON sara_interest (last_acted_at NULLS FIRST)"
    )
    op.execute(
        "CREATE INDEX ix_sara_interest_embedding "
        "ON sara_interest USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sara_interest_embedding")
    op.execute("DROP INDEX IF EXISTS ix_sara_interest_acted")
    op.execute("DROP INDEX IF EXISTS ix_sara_interest_weight")
    op.drop_table("sara_interest")
