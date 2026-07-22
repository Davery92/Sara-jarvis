"""Dreams (§3.8) + readiness engine (§6.2) + trust matrix (§3.7) + hourly patterns.

- autonomy_trust table (graduated-autonomy trust contract).
- nightly-dream-cycle (02:00 ET), morning-readiness-compute (05:15 ET, sensed-wake-ish).
- Flip the pattern proactive check to HOURLY so its ±30-min window can actually
  overlap learned pattern times (D2 note (a)).

Revision ID: 117_dreams_readiness_trust
Revises: 116_curiosity
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "117_dreams_readiness_trust"
down_revision = "116_curiosity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "autonomy_trust",
        sa.Column("action_class", sa.String, primary_key=True),
        sa.Column("granted_level", sa.Integer, nullable=False, server_default="1"),
        sa.Column("executions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("accepts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("declines", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_demoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    bind = op.get_bind()
    jobs = [
        ("nightly-dream-cycle", "Dream cycle", "app.tasks.dreams.run_dream_cycle",
         "Counterfactual replay + tomorrow rehearsal + PKG recombination (§3.8). Offline, journal-only.",
         "0 2 * * *"),
        ("morning-readiness-compute", "Readiness compute", "app.tasks.readiness.compute",
         "Nightly readiness = f(sleep, HRV, RHR vs personal baselines) → morning_readiness (§6.2).",
         "15 5 * * *"),
    ]
    for key, name, task, desc, cron in jobs:
        bind.execute(sa.text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
            ) VALUES (
                :key, :name, :desc, 'cognition', :task,
                'cron', :cron, NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600, TRUE, TRUE, 'system', 'user'
            ) ON CONFLICT (key) DO NOTHING
        """), {"key": key, "name": name, "desc": desc, "task": task, "cron": cron})

    # D2 (a): the pattern proactive check ran at fixed clock times that could
    # never fall within ±30 min of learned pattern times. Hourly overlaps them.
    bind.execute(sa.text(
        "UPDATE scheduled_job SET schedule_kind='cron', cron_expr='0 * * * *', interval_seconds=NULL "
        "WHERE key = 'morning-proactive-check'"
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM scheduled_job WHERE key IN ('nightly-dream-cycle','morning-readiness-compute')"
    ))
    op.drop_table("autonomy_trust")
