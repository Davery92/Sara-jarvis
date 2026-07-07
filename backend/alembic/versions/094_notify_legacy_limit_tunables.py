"""Category-limit tunables + legacy-limits gate — SARA_UNLEASHED Phase T.3.

Converts the hand-tuned `category_limits` dict in
unified_notification._check_dedup from a Python literal into DB-backed
tunables — the first step of collapsing five uncoordinated suppression
layers into two (the gate + the learned attention layer). Same default
values, zero behavior change on its own.

Also seeds `notify.legacy_limits` (default True/on): while True, the
legacy category-limit check and notification_tuner keep enforcing exactly
as before AND log a `limit_divergence` line whenever they'd act, so a week
of real divergence data exists before anyone flips this to False and lets
the gate + learned buzz decision take over for real.

Revision ID: 094_notify_legacy_limit_tunables
Revises: 093_workout_log_exercise_fk
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa
import json as _json

revision = "094_notify_legacy_limit_tunables"
down_revision = "093_workout_log_exercise_fk"
branch_labels = None
depends_on = None

# (key, display_name, description, category, value_type, default, min, max, unit)
SEED_TUNABLES = [
    ("notify.legacy_limits", "Legacy suppression layers active",
     "When on, notification_tuner and the per-category rate-limit dict still enforce "
     "(exactly as before Phase T.3) and log divergences against the learned attention "
     "layer. Turn off only after a week of clean divergence logs — this is the switch "
     "that hands control to the gate + theta.",
     "notifications", "bool", True, None, None, None),

    ("notify.category_limit.home.max_count", "Home category limit (count)", "Max 'home' notifications per window.", "notifications", "int", 3, 1, 20, "count"),
    ("notify.category_limit.home.window_hours", "Home category limit (window)", "Window (hours) for the home category limit.", "notifications", "float", 6.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.security.max_count", "Security category limit (count)", "Max 'security' notifications per window.", "notifications", "int", 4, 1, 20, "count"),
    ("notify.category_limit.security.window_hours", "Security category limit (window)", "Window (hours) for the security category limit.", "notifications", "float", 6.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.checkin.max_count", "Checkin category limit (count)", "Max 'checkin' notifications per window.", "notifications", "int", 1, 1, 20, "count"),
    ("notify.category_limit.checkin.window_hours", "Checkin category limit (window)", "Window (hours) for the checkin category limit.", "notifications", "float", 6.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.weather.max_count", "Weather category limit (count)", "Max 'weather' notifications per window.", "notifications", "int", 2, 1, 20, "count"),
    ("notify.category_limit.weather.window_hours", "Weather category limit (window)", "Window (hours) for the weather category limit.", "notifications", "float", 8.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.health.max_count", "Health category limit (count)", "Max 'health' notifications per window.", "notifications", "int", 1, 1, 20, "count"),
    ("notify.category_limit.health.window_hours", "Health category limit (window)", "Window (hours) for the health category limit.", "notifications", "float", 24.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.fitness.max_count", "Fitness category limit (count)", "Max 'fitness' notifications per window.", "notifications", "int", 1, 1, 20, "count"),
    ("notify.category_limit.fitness.window_hours", "Fitness category limit (window)", "Window (hours) for the fitness category limit.", "notifications", "float", 24.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.wellness.max_count", "Wellness category limit (count)", "Max 'wellness' notifications per window.", "notifications", "int", 1, 1, 20, "count"),
    ("notify.category_limit.wellness.window_hours", "Wellness category limit (window)", "Window (hours) for the wellness category limit.", "notifications", "float", 24.0, 1.0, 48.0, "hours"),

    ("notify.category_limit.acs_discovery.max_count", "ACS discovery category limit (count)", "Max 'acs_discovery' notifications per window.", "notifications", "int", 1, 1, 20, "count"),
    ("notify.category_limit.acs_discovery.window_hours", "ACS discovery category limit (window)", "Window (hours) for the acs_discovery category limit.", "notifications", "float", 4.0, 1.0, 48.0, "hours"),
]


def upgrade():
    bind = op.get_bind()
    for (key, display_name, description, category, value_type, default, min_v, max_v, unit) in SEED_TUNABLES:
        bind.execute(
            sa.text("""
                INSERT INTO tunable_setting (
                    key, display_name, description, category, value_type,
                    value, default_value, min_value, max_value, unit
                ) VALUES (
                    :key, :display_name, :description, :category, :value_type,
                    CAST(:default_v AS jsonb), CAST(:default_v AS jsonb),
                    CAST(:min_v AS jsonb), CAST(:max_v AS jsonb), :unit
                )
                ON CONFLICT (key) DO NOTHING
            """),
            {
                "key": key, "display_name": display_name, "description": description,
                "category": category, "value_type": value_type,
                "default_v": _json.dumps(default),
                "min_v": _json.dumps(min_v) if min_v is not None else None,
                "max_v": _json.dumps(max_v) if max_v is not None else None,
                "unit": unit,
            },
        )


def downgrade():
    bind = op.get_bind()
    for (key, *_rest) in SEED_TUNABLES:
        bind.execute(sa.text("DELETE FROM tunable_setting WHERE key = :key"), {"key": key})
