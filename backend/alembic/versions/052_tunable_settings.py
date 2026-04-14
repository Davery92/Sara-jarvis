"""Add tunable_setting table for editable system knobs.

Revision ID: 052_tunable_settings
Revises: 051_scheduled_jobs
Create Date: 2026-04-08

Stores user-editable knobs for subsystems like notifications, ACS, and the
morning brief. Read by `app.services.tunables.get_tunable()` with a 60s
cache. Edited via `/api/settings/tunables` and the Settings UI on web + iOS.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import inspect
import json as _json


revision = "052_tunable_settings"
down_revision = "051_scheduled_jobs"
branch_labels = None
depends_on = None


def table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


# Each row: (key, display_name, description, category, value_type, default_value,
#            min_value, max_value, unit)
SEED_TUNABLES = [
    # ── Notification cooldowns (hours per category) ──
    ("notification.cooldown.checkin_hours", "Check-in cooldown",
     "Minimum hours between proactive check-ins from Sara.",
     "notifications", "float", 2.0, 0.0, 48.0, "hours"),
    ("notification.cooldown.general_hours", "General cooldown",
     "Default cooldown for non-categorized proactive notifications.",
     "notifications", "float", 2.0, 0.0, 48.0, "hours"),
    ("notification.cooldown.calendar_hours", "Calendar cooldown",
     "Min hours between calendar notifications.",
     "notifications", "float", 24.0, 0.0, 48.0, "hours"),
    ("notification.cooldown.email_hours", "Email cooldown",
     "Min hours between email notifications.",
     "notifications", "float", 4.0, 0.0, 48.0, "hours"),
    ("notification.cooldown.health_hours", "Health cooldown",
     "Min hours between health/fitness notifications.",
     "notifications", "float", 24.0, 0.0, 48.0, "hours"),

    # ── Quiet hours ──
    ("notification.quiet_hours.start", "Quiet hours start",
     "Hour of day (0-23, local time) when Sara stops most proactive notifications.",
     "notifications", "int", 23, 0, 23, "hour of day"),
    ("notification.quiet_hours.end", "Quiet hours end",
     "Hour of day (0-23, local time) when Sara resumes proactive notifications.",
     "notifications", "int", 5, 0, 23, "hour of day"),

    # ── ACS thresholds ──
    ("acs.salience_threshold", "Salience threshold",
     "Accumulated salience score required to trigger deliberation. Lower = more reactive Sara, higher = quieter.",
     "acs", "float", 1.5, 0.1, 10.0, "salience units"),
    ("acs.max_deliberation_gap_hours", "Max deliberation gap",
     "Maximum hours between deliberations (safety net for periodic-deliberation-fallback).",
     "acs", "float", 1.5, 0.1, 24.0, "hours"),

    # ── Morning brief tone & length ──
    ("morning_brief.target_word_count_min", "Brief min word count",
     "Minimum target length for the morning brief LLM output.",
     "morning_brief", "int", 300, 50, 2000, "words"),
    ("morning_brief.target_word_count_max", "Brief max word count",
     "Maximum target length for the morning brief LLM output.",
     "morning_brief", "int", 500, 100, 3000, "words"),
    ("morning_brief.tone_directive", "Brief tone",
     "Free-text tone directive injected into the morning brief LLM prompt. e.g. 'Warm and natural morning energy.'",
     "morning_brief", "string", "Warm and natural morning energy.", None, None, None),
]


def upgrade():
    if not table_exists("tunable_setting"):
        op.create_table(
            "tunable_setting",
            sa.Column("key", sa.String(length=120), primary_key=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=50), nullable=False, server_default="general"),
            sa.Column("value_type", sa.String(length=20), nullable=False),  # int, float, string, bool, json
            sa.Column("value", JSONB(), nullable=False),
            sa.Column("default_value", JSONB(), nullable=False),
            sa.Column("min_value", JSONB(), nullable=True),
            sa.Column("max_value", JSONB(), nullable=True),
            sa.Column("unit", sa.String(length=50), nullable=True),
            sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_tunable_setting_category", "tunable_setting", ["category"])

    bind = op.get_bind()
    for (key, display_name, description, category, value_type, default,
         min_v, max_v, unit) in SEED_TUNABLES:
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
                "key": key,
                "display_name": display_name,
                "description": description,
                "category": category,
                "value_type": value_type,
                "default_v": _json.dumps(default),
                "min_v": _json.dumps(min_v) if min_v is not None else None,
                "max_v": _json.dumps(max_v) if max_v is not None else None,
                "unit": unit,
            },
        )


def downgrade():
    if table_exists("tunable_setting"):
        op.drop_index("ix_tunable_setting_category", "tunable_setting")
        op.drop_table("tunable_setting")
