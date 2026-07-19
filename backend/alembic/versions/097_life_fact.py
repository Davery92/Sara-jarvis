"""Autobiographical life facts — Brain Alignment H3.

David's stable life rhythms as consultable, durable facts (not learned
patterns with confidence). Stated facts outrank inferred ones and are
consulted before anything schedules a time on his behalf.

Revision ID: 097_life_fact
Revises: 096_stimulus_habituation
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "097_life_fact"
down_revision = "096_stimulus_habituation"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "life_fact" not in insp.get_table_names():
        op.create_table(
            "life_fact",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            # Controlled vocabulary — see app/services/life_facts.py LIFE_FACT_PREDICATES
            sa.Column("predicate", sa.String(64), nullable=False),
            sa.Column("value_text", sa.String(255), nullable=False),
            # NULL weekday = applies every day; 0=Mon..6=Sun otherwise
            sa.Column("weekday", sa.Integer(), nullable=True),
            # 'stated' (David said it) > 'inferred' (seeded from rhythm data)
            sa.Column("source", sa.String(16), nullable=False, server_default="inferred"),
            sa.Column("authority", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.6"),
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("user_id", "predicate", "weekday", name="uq_life_fact_user_predicate_weekday"),
        )
        op.create_index("ix_life_fact_user", "life_fact", ["user_id"])


def downgrade():
    op.drop_index("ix_life_fact_user", table_name="life_fact")
    op.drop_table("life_fact")
