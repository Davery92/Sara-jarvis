"""Curiosity / intrinsic motivation (§3.5) — nightly generate + pursue.

Registers the nightly curiosity sweep: mint candidate goals from repeated
prediction errors + calibration gaps, then pursue the single best within budget
(≤1 active goal, 1 local-Qwen investigation) → journal. Runs at 01:30 ET, in the
mid-sleep window (internal, no interruption).

Revision ID: 116_curiosity
Revises: 115_ml_inprocess_training
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "116_curiosity"
down_revision = "115_ml_inprocess_training"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
        ) VALUES (
            'curiosity-sweep',
            'Curiosity sweep',
            'Nightly: generate curiosity goals from repeated prediction errors + calibration gaps, pursue the best within budget via a bounded local-Qwen investigation, land the finding in the journal (§3.5).',
            'cognition',
            'app.tasks.curiosity.run_curiosity',
            'cron', '30 1 * * *', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'cognitive', 600, TRUE, TRUE, 'system', 'user'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'curiosity-sweep'"))
