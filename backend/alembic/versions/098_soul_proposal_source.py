"""Graduation-ladder columns on soul_change_proposals — Brain Alignment H7.2.

`source_ref` links a proposal back to the PKG fact that generated it (so it can
be marked internalized on approval). `kind` distinguishes style-only proposals
(auto-approvable after 14 days) from identity-level ones (always consented).

Revision ID: 098_soul_proposal_source
Revises: 097_life_fact
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "098_soul_proposal_source"
down_revision = "097_life_fact"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("soul_change_proposals")}
    if "source_ref" not in cols:
        op.add_column("soul_change_proposals", sa.Column("source_ref", sa.String(128), nullable=True))
    if "kind" not in cols:
        op.add_column("soul_change_proposals", sa.Column("kind", sa.String(20), nullable=False, server_default="identity"))
    if "evidence_count" not in cols:
        op.add_column("soul_change_proposals", sa.Column("evidence_count", sa.Integer(), nullable=True))


def downgrade():
    for col in ("source_ref", "kind", "evidence_count"):
        try:
            op.drop_column("soul_change_proposals", col)
        except Exception:
            pass
