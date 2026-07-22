"""Prediction loop (§3.2) — extend `prediction` for windowed, matchable predictions.

The predictive-coding flip: Sara maintains cheap explicit predictions about the
next hours; confirmed predictions are silence, violated predictions are salience.
The existing `prediction` table had statement/domain/confidence/outcome but no
*window* to match against and no structured predicted/actual values. This adds
them, plus registers the generate/match/calibration jobs.

Revision ID: 113_prediction_loop
Revises: 112_held_notification
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "113_prediction_loop"
down_revision = "112_held_notification"
branch_labels = None
depends_on = None


_DAVID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


def upgrade():
    with op.batch_alter_table("prediction") as b:
        b.add_column(sa.Column("user_id", sa.String, nullable=True))
        b.add_column(sa.Column("prediction_key", sa.String, nullable=True))
        b.add_column(sa.Column("source", sa.String, nullable=True))  # rhythm|pattern|calendar|baseline
        b.add_column(sa.Column("window_start", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("window_end", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("predicted_value", postgresql.JSONB, nullable=True))
        b.add_column(sa.Column("matched_value", postgresql.JSONB, nullable=True))
        b.add_column(sa.Column("salience_emitted", sa.Boolean, server_default=sa.text("false"), nullable=False))

    op.execute(f"UPDATE prediction SET user_id = '{_DAVID}' WHERE user_id IS NULL")
    op.create_index("ix_prediction_pending", "prediction", ["outcome", "window_end"])
    op.create_index("ix_prediction_key", "prediction", ["prediction_key"])

    bind = op.get_bind()
    jobs = [
        ("prediction-generate", "Prediction: generate daily",
         "Mint the day's predictions from learned rhythm + high-confidence home patterns (§3.2). Internal, no push.",
         "app.tasks.predictions.generate_daily", "cron", "30 4 * * *", None),
        ("prediction-match", "Prediction: match/resolve",
         "Every 15 min: resolve pending predictions confirmed/violated/expired; violations feed salience (§3.2).",
         "app.tasks.predictions.match_pending", "interval", None, 900),
        ("prediction-calibration", "Prediction: weekly calibration",
         "Sunday: grade whether stated confidence matched actual hit-rate per domain (§3.9).",
         "app.tasks.predictions.calibration_report", "cron", "0 10 * * 0", None),
    ]
    for key, name, desc, task, kind, cron, interval in jobs:
        bind.execute(sa.text("""
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
            ) VALUES (
                :key, :name, :desc, 'cognition', :task,
                :kind, :cron, :interval, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300, TRUE, TRUE, 'system', 'user'
            ) ON CONFLICT (key) DO NOTHING
        """), {"key": key, "name": name, "desc": desc, "task": task,
               "kind": kind, "cron": cron, "interval": interval})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM scheduled_job WHERE key IN "
        "('prediction-generate','prediction-match','prediction-calibration')"
    ))
    op.drop_index("ix_prediction_key", table_name="prediction")
    op.drop_index("ix_prediction_pending", table_name="prediction")
    with op.batch_alter_table("prediction") as b:
        for c in ("salience_emitted", "matched_value", "predicted_value",
                  "window_end", "window_start", "source", "prediction_key", "user_id"):
            b.drop_column(c)
