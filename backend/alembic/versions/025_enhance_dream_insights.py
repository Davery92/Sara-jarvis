"""Enhance dream_insight table for LLM-powered insights

Revision ID: 025_enhance_dream_insights
Revises: 024_token_usage
Create Date: 2025-12-12

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '025_enhance_dream_insights'
down_revision = '024_token_usage'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns for enhanced insight tracking

    # surface_strategy: proactive, contextual, passive
    op.add_column('dream_insight', sa.Column(
        'surface_strategy',
        sa.String(50),
        nullable=True,
        server_default='contextual'
    ))

    # evidence: what conversations/data support this insight
    op.add_column('dream_insight', sa.Column(
        'evidence',
        sa.Text(),
        nullable=True
    ))

    # expiry_at: when this insight becomes stale
    op.add_column('dream_insight', sa.Column(
        'expiry_at',
        sa.DateTime(),
        nullable=True
    ))

    # surfaced_count: how many times shown to user
    op.add_column('dream_insight', sa.Column(
        'surfaced_count',
        sa.Integer(),
        nullable=True,
        server_default='0'
    ))

    # last_surfaced_at: when it was last shown
    op.add_column('dream_insight', sa.Column(
        'last_surfaced_at',
        sa.DateTime(),
        nullable=True
    ))

    # Add index for efficient querying of surfaceable insights
    # Note: No partial index with NOW() since it's not immutable - filter at query time
    op.create_index(
        'idx_dream_insight_surface',
        'dream_insight',
        ['user_id', 'surface_strategy', 'surfaced_count']
    )

    # Update existing insights with default values
    op.execute("""
        UPDATE dream_insight
        SET surface_strategy = 'contextual',
            surfaced_count = 0
        WHERE surface_strategy IS NULL
    """)


def downgrade():
    op.drop_index('idx_dream_insight_surface', table_name='dream_insight')
    op.drop_column('dream_insight', 'last_surfaced_at')
    op.drop_column('dream_insight', 'surfaced_count')
    op.drop_column('dream_insight', 'expiry_at')
    op.drop_column('dream_insight', 'evidence')
    op.drop_column('dream_insight', 'surface_strategy')
