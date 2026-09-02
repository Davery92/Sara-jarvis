"""Nightly truth maintenance keeps a receipt.

Ground-truth plan, Phase 7. The nightly job expires stale threads, closes dead
reminders and audits the things that quietly rot — governing docs, life-fact
sanity, predicates with two live values, meetings claimed with no calendar event.
Doing that silently would just be a second unaccountable process; the report row
is what makes it auditable, and what the morning brief reads its one line from.

Revision ID: 150_truth_maintenance_report
Revises: 149_thread_due_provenance
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa

revision = "150_truth_maintenance_report"
down_revision = "149_thread_due_provenance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS truth_maintenance_report (
            id           BIGSERIAL PRIMARY KEY,
            user_id      VARCHAR(255) NOT NULL,
            ran_for_date DATE NOT NULL,
            counts       JSONB NOT NULL DEFAULT '{}'::jsonb,
            flags        JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    # One report per user per night; a re-run updates rather than duplicating.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_truth_maintenance_user_date
        ON truth_maintenance_report (user_id, ran_for_date)
    """))
    bind.execute(sa.text("""
        INSERT INTO scheduled_job
            (key, display_name, description, category, task_name, schedule_kind,
             cron_expr, timezone, queue, enabled, editable, source, visibility)
        VALUES
            ('truth-maintenance',
             'Nightly truth maintenance',
             'Expires stale threads, reminders and commitments; audits life-fact '
             'sanity, contradictory predicates, stale governing docs and '
             'half-detected meetings. Deterministic — no LLM.',
             'system',
             'app.tasks.truth_maintenance.run_truth_maintenance',
             'cron', '50 3 * * *', 'America/New_York', 'maintenance',
             TRUE, TRUE, 'system', 'user')
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'truth-maintenance'"))
    bind.execute(sa.text("DROP TABLE IF EXISTS truth_maintenance_report"))
