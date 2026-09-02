"""Every thread deadline names the thing that vouched for it.

Ground-truth invariant 1 ("no invented time"): a `world_thread.due_at` may only
come from a calendar event, a producer row that already carries a real time, an
explicit datetime written in the source text, or David's own words. This column
records which of those it was, so a wrong deadline can be traced to the thing
that claimed it instead of to a model's guess.

Rows whose deadline predates the invariant are backfilled as 'legacy:unverified'
— they are exactly the population the nightly truth job expires.

Revision ID: 149_thread_due_provenance
Revises: 148_research_single_flight
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa

revision = "149_thread_due_provenance"
down_revision = "148_research_single_flight"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        ALTER TABLE world_thread
        ADD COLUMN IF NOT EXISTS due_provenance VARCHAR(200)
    """))
    bind.execute(sa.text("""
        UPDATE world_thread
        SET due_provenance = 'legacy:unverified'
        WHERE due_at IS NOT NULL AND due_provenance IS NULL
    """))
    # A thread with no deadline still needs a review date, or nothing ever
    # revisits it. Threads created before this migration had neither.
    bind.execute(sa.text("""
        UPDATE world_thread
        SET next_review_at = created_at + INTERVAL '3 days'
        WHERE due_at IS NULL AND next_review_at IS NULL
    """))


def downgrade():
    op.get_bind().execute(sa.text(
        "ALTER TABLE world_thread DROP COLUMN IF EXISTS due_provenance"
    ))
