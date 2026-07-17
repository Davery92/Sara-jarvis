"""ML feature store foundation (Desktop Jarvis Overhaul C1/C2).

Adds:
- `desktop_focus_span`: durable persistence of DESKTOP_FOCUS_SPAN events —
  today these only flow transiently through the salience/working-memory
  pipeline; the feature store needs real per-app time-on-task history.
- `voice_interaction_log`: durable per-conversation record from the Jetson
  voice pipeline (turns, duration) — today only flows through the event bus.
- `ml_feature_daily`: one row per user-day of aggregated features.
- `ml_notification_outcome`: per-notification features-at-send-time + outcome.
- `ml_prediction_log`: every shadow/live model inference, for eval.
- `ml_model_version`: model registry (family, version, artifact, metrics, status).

Registers the nightly `materialize-ml-features` job at 2:30 AM ET (after
consolidation at 2:00 AM, before daily-rhythm recompute at 3:45 AM).

Revision ID: 087_ml_feature_store
Revises: 086_system_wiring_check
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "087_ml_feature_store"
down_revision = "086_system_wiring_check"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = insp.get_table_names()

    if "desktop_focus_span" not in existing:
        op.create_table(
            "desktop_focus_span",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_id", sa.String(), nullable=True),
            sa.Column("app", sa.String(), nullable=True),
            sa.Column("window", sa.String(), nullable=True),
            sa.Column("domain", sa.String(), nullable=True),
            sa.Column("derived_state", sa.String(), nullable=True),
            sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("keyboard_events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mouse_events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_desktop_focus_span_user_start", "desktop_focus_span", ["user_id", "start_ts"])

    if "voice_interaction_log" not in existing:
        op.create_table(
            "voice_interaction_log",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("source", sa.String(), nullable=False, server_default="jetson_voice"),
        )
        op.create_index("ix_voice_interaction_log_user_started", "voice_interaction_log", ["user_id", "started_at"])

    if "ml_feature_daily" not in existing:
        op.create_table(
            "ml_feature_daily",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("feature_date", sa.Date(), nullable=False),
            # Desktop activity aggregates per app-category + first/last activity
            sa.Column("focus_seconds_by_category", JSONB(), nullable=True),
            sa.Column("first_desktop_activity_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_desktop_activity_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_focus_seconds", sa.Integer(), nullable=False, server_default="0"),
            # Location timeline summary
            sa.Column("location_summary", JSONB(), nullable=True),
            # Sleep/health
            sa.Column("sleep_hours", sa.Float(), nullable=True),
            sa.Column("hrv", sa.Float(), nullable=True),
            sa.Column("resting_heart_rate", sa.Float(), nullable=True),
            # Workout/food flags
            sa.Column("workout_logged", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("meals_logged", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_calories", sa.Float(), nullable=True),
            # Calendar load
            sa.Column("calendar_event_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("calendar_busy_seconds", sa.Integer(), nullable=False, server_default="0"),
            # Notifications sent/engagement
            sa.Column("notifications_sent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notifications_engaged", sa.Integer(), nullable=False, server_default="0"),
            # Voice
            sa.Column("voice_interactions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("voice_turns", sa.Integer(), nullable=False, server_default="0"),
            # Day-level classification (populated by the next-block/rhythm models later)
            sa.Column("day_of_week", sa.Integer(), nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "feature_date", name="uq_ml_feature_daily_user_date"),
        )
        op.create_index("ix_ml_feature_daily_user_date", "ml_feature_daily", ["user_id", "feature_date"])

    if "ml_notification_outcome" not in existing:
        op.create_table(
            "ml_notification_outcome",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("notification_log_id", sa.String(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("hour", sa.Integer(), nullable=True),
            sa.Column("day_of_week", sa.Integer(), nullable=True),
            sa.Column("activity_state", sa.String(), nullable=True),
            sa.Column("interruptibility_score", sa.Float(), nullable=True),
            sa.Column("device", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("location", sa.String(), nullable=True),
            sa.Column("outcome", sa.String(), nullable=True),  # opened|acted|dismissed|ignored
            sa.Column("outcome_latency_seconds", sa.Float(), nullable=True),
            sa.Column("features", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ml_notification_outcome_user_sent", "ml_notification_outcome", ["user_id", "sent_at"])

    if "ml_prediction_log" not in existing:
        op.create_table(
            "ml_prediction_log",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("model_family", sa.String(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("features_hash", sa.String(), nullable=True),
            sa.Column("features", JSONB(), nullable=True),
            sa.Column("prediction", JSONB(), nullable=True),
            sa.Column("ground_truth", JSONB(), nullable=True),
            sa.Column("mode", sa.String(), nullable=False, server_default="shadow"),  # shadow|live
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ml_prediction_log_family_created", "ml_prediction_log", ["model_family", "created_at"])

    if "ml_model_version" not in existing:
        op.create_table(
            "ml_model_version",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("family", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("artifact_key", sa.String(), nullable=True),
            sa.Column("metrics", JSONB(), nullable=True),
            sa.Column("metadata_json", JSONB(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="candidate"),  # candidate|shadow|active|retired
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("family", "version", name="uq_ml_model_version_family_version"),
        )
        op.create_index("ix_ml_model_version_family_status", "ml_model_version", ["family", "status"])

    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'materialize-ml-features',
                'Materialize ML Features',
                'Nightly rollup of desktop focus, location, sleep/health, workout/food, calendar, notification, and voice activity into one feature row per user-day for the ML training pipeline.',
                'learning',
                'app.tasks.ml.materialize_features',
                'cron', '30 2 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 1800,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'sync-ml-notification-outcomes',
                'Sync ML Notification Outcomes',
                'Hourly: back-fill ml_notification_outcome.outcome from notification_log engagement columns, so the interruptibility_v2/notification_value models have fresh labels to train on.',
                'learning',
                'app.tasks.ml.sync_notification_outcomes',
                'interval', NULL, 3600, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES (
                'ml-retrain-all',
                'Retrain All ML Models',
                'Nightly: queue one train_model job per model family (interruptibility_v2, notification_value, next_block, rhythm_forecaster) against the latest ml_feature_daily rows.',
                'learning',
                'app.tasks.ml.retrain_all',
                'cron', '15 3 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 1800,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key IN ('materialize-ml-features', 'ml-retrain-all', 'sync-ml-notification-outcomes')"))
    op.drop_table("ml_model_version")
    op.drop_table("ml_prediction_log")
    op.drop_table("ml_notification_outcome")
    op.drop_index("ix_ml_feature_daily_user_date", table_name="ml_feature_daily")
    op.drop_table("ml_feature_daily")
    op.drop_index("ix_voice_interaction_log_user_started", table_name="voice_interaction_log")
    op.drop_table("voice_interaction_log")
    op.drop_index("ix_desktop_focus_span_user_start", table_name="desktop_focus_span")
    op.drop_table("desktop_focus_span")
