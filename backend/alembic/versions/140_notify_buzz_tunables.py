"""Learned-buzz gate thresholds as tunables — NOTIFICATION_DELIVERY_FIX_PLAN_2026_08_17 Phase 3.

The learned-buzz gate (_learned_buzz_decision in unified_notification.py)
was unreachable: it only ever pushed on a 30-day engagement rate >= 40%,
and engagement only accrues from pushes — a category stuck below 40% could
never climb out (verified live 2026-08-17: general 15%, checkin 12%,
agent_task 6%, no active category qualifying). This migration seeds the
thresholds for the revised gate (engaged_rate OR read_rate, plus a
silent-category grace path) as DB-backed tunables instead of literals, same
pattern as migration 094's category-limit tunables.

Revision ID: 140_notify_buzz_tunables
Revises: 139_workout_session_active_link
Create Date: 2026-08-17
"""
from alembic import op
import sqlalchemy as sa
import json as _json

revision = "140_notify_buzz_tunables"
down_revision = "139_workout_session_active_link"
branch_labels = None
depends_on = None

# (key, display_name, description, category, value_type, default, min, max, unit)
SEED_TUNABLES = [
    ("notification.buzz.engaged_rate_threshold", "Buzz engagement-rate threshold",
     "A category's trailing 30-day engaged rate must clear this to earn a normal/low-priority push.",
     "notifications", "float", 0.25, 0.0, 1.0, "ratio"),

    ("notification.buzz.read_rate_threshold", "Buzz read-rate threshold",
     "A category's trailing 30-day read rate must clear this to earn a normal/low-priority push "
     "(alternative path to engaged_rate_threshold, since reading is a real signal that doesn't "
     "require a push to have happened first).",
     "notifications", "float", 0.5, 0.0, 1.0, "ratio"),

    ("notification.buzz.interruptibility_threshold", "Buzz interruptibility threshold",
     "Minimum current interruptibility score required to actually deliver a qualified push.",
     "notifications", "float", 0.5, 0.0, 1.0, "score"),

    ("notification.buzz.silent_days_threshold", "Buzz silent-category grace window",
     "A category that hasn't had an actual push in this many days gets one grace push/day to "
     "re-earn stats, even if its rates are below threshold.",
     "notifications", "float", 7.0, 1.0, 30.0, "days"),
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
