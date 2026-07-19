"""Stimulus habituation table — Brain Alignment H2.

Revision ID: 096_stimulus_habituation
Revises: 095_sync_sent_items_job
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "096_stimulus_habituation"
down_revision = "095_sync_sent_items_job"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "stimulus_habituation" not in insp.get_table_names():
        op.create_table(
            "stimulus_habituation",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generator", sa.String(80), nullable=False),
            sa.Column("stimulus_key", sa.String(255), nullable=False),
            sa.Column("strength", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_engaged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_decay_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("generator", "stimulus_key", name="uq_stimulus_habituation_generator_key"),
        )
        op.create_index(
            "ix_stimulus_habituation_generator",
            "stimulus_habituation",
            ["generator", "strength"],
        )


def downgrade():
    op.drop_index("ix_stimulus_habituation_generator", table_name="stimulus_habituation")
    op.drop_table("stimulus_habituation")
