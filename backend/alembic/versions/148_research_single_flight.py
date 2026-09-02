"""Single-flight research: track the worker + allow non-terminal outcomes.

The 2026-09-01 Salem incident: two research agents ran concurrently against the
Mac Studio bg lane, which 507'd, and all three plans were then marked
`complete` with zero output. Cancelling a plan needs the Celery task id so the
worker can actually be revoked (a status flip alone leaves it grinding), and
the executor needs somewhere to park a plan that hit a sick lane.

`research_plan.status` has no CHECK constraint, so the new values
(`cancelled`, `stalled`, `partial`) need no schema change — they are documented
in app.services.agent_activity.RESEARCH_STATUS_MAP.

Revision ID: 148_research_single_flight
Revises: 147_interpreter_attempt_cap
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa

revision = "148_research_single_flight"
down_revision = "147_interpreter_attempt_cap"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        ALTER TABLE research_plan
        ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(64)
    """))
    # The create-time single-flight guard runs on every chat handoff; it must
    # never table-scan research_plan.
    op.get_bind().execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_research_plan_user_live
        ON research_plan (user_id, status)
        WHERE status IN ('draft','running','stuck','stalled','paused')
    """))
    # Reap plans abandoned before this migration. The guard refuses to start new
    # research while a live-looking row exists, and prod had a `stuck` plan from
    # 2026-08-19 whose worker was long gone — left alone it would have wedged
    # research permanently. Nothing older than the Celery hard limit (~6.1h) can
    # still be running.
    op.get_bind().execute(sa.text("""
        UPDATE research_plan
        SET status = 'failed',
            error_log = COALESCE(error_log, '') ||
                '\nAbandoned before the single-flight migration; no worker was running it.',
            updated_at = NOW()
        WHERE status IN ('draft','running','stuck','paused')
          AND COALESCE(updated_at, created_at) < NOW() - INTERVAL '6 hours'
    """))


def downgrade():
    op.get_bind().execute(sa.text("DROP INDEX IF EXISTS ix_research_plan_user_live"))
    op.get_bind().execute(sa.text(
        "ALTER TABLE research_plan DROP COLUMN IF EXISTS celery_task_id"
    ))
