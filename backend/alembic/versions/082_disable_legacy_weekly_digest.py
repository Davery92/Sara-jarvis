"""Disable the legacy non-pattern-aware weekly digest.

`scheduled_job` has two weekly digests registered: the old `weekly-digest`
(Sun 10 AM ET, `app.tasks.autonomy.weekly_learning_digest`) and the new
Phase 6 pattern-aware `learning-digest-weekly` (Sun 7 PM ET,
`app.tasks.learning_digest.send_weekly_digest`). The old one reads no
pattern/theta/rhythm tables and would otherwise double-send every Sunday.
Disable it rather than delete, so the row stays for history/rollback.

Revision ID: 082_disable_legacy_weekly_digest
Revises: 081_location_discovery_nudges
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "082_disable_legacy_weekly_digest"
down_revision = "081_location_discovery_nudges"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE scheduled_job SET enabled = false WHERE key = 'weekly-digest'")
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE scheduled_job SET enabled = true WHERE key = 'weekly-digest'")
    )
