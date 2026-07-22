"""In-process ML training job (§4.2.5 / D1) — nightly retrain, replaces phantom plane.

Registers the nightly `ml-retrain-inprocess` task that actually trains the
notification_value model (the old ml-retrain-all queued into a void). Runs at
02:45 ET, after the 2:30 feature-store materialization.

Revision ID: 115_ml_inprocess_training
Revises: 114_belief_ladder
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "115_ml_inprocess_training"
down_revision = "114_belief_ladder"
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
            'ml-retrain-inprocess',
            'ML: retrain (in-process)',
            'Nightly in-process training of model families (notification_value) from labeled outcomes; cross-validated, promoted only if it beats the current model. Replaces the phantom Redis job plane (D1).',
            'cognition',
            'app.tasks.ml_train.train_all',
            'cron', '45 2 * * *', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'cognitive', 600, TRUE, TRUE, 'system', 'user'
        ) ON CONFLICT (key) DO NOTHING
    """))
    # Retire the phantom nightly retrain that queued jobs no worker consumed.
    bind.execute(sa.text(
        "UPDATE scheduled_job SET enabled = FALSE "
        "WHERE key = 'ml-retrain-all' AND task_name LIKE '%ml.retrain%'"
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'ml-retrain-inprocess'"))
    bind.execute(sa.text("UPDATE scheduled_job SET enabled = TRUE WHERE key = 'ml-retrain-all'"))
