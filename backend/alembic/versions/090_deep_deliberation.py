"""Deep deliberation — SARA_UNLEASHED Phase C.3.

Registers the 2x/day deep-deliberation runs on the strong model
(claude-sonnet-5 by default, tunable `deliberation.deep_model`), scheduled
15 minutes after the existing afternoon/evening consolidation jobs (2:00 PM
and 9:00 PM ET) so the deep run sees a freshly-consolidated picture.

Revision ID: 090_deep_deliberation
Revises: 089_assistant_verbs_sweep
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "090_deep_deliberation"
down_revision = "089_assistant_verbs_sweep"
branch_labels = None
depends_on = None

_JOBS = [
    (
        "deep-deliberation-afternoon",
        "Deep Deliberation (Afternoon)",
        "14:15 ET deep deliberation on the strong model — wider observation window, higher task-proposal cap.",
        "15 14 * * *",
    ),
    (
        "deep-deliberation-evening",
        "Deep Deliberation (Evening)",
        "21:15 ET deep deliberation on the strong model — wider observation window, higher task-proposal cap.",
        "15 21 * * *",
    ),
]


def upgrade():
    bind = op.get_bind()
    for key, display_name, description, cron_expr in _JOBS:
        bind.execute(
            sa.text(
                """
                INSERT INTO scheduled_job (
                    key, display_name, description, category, task_name,
                    schedule_kind, cron_expr, interval_seconds, timezone,
                    args, kwargs, queue, expires_seconds,
                    enabled, editable, source, visibility
                ) VALUES (
                    :key, :display_name, :description, 'cognitive',
                    'app.tasks.autonomy.deep_deliberation',
                    'cron', :cron_expr, NULL, 'America/New_York',
                    '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                    TRUE, TRUE, 'system', 'system'
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {"key": key, "display_name": display_name, "description": description, "cron_expr": cron_expr},
        )


def downgrade():
    bind = op.get_bind()
    for key, _, _, _ in _JOBS:
        bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = :key"), {"key": key})
