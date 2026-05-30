"""Narrator: seed tunable cooldown knobs for the noisy severities.

Revision ID: 068_narrator_tunables
Revises: 067_narrator_beat
Create Date: 2026-05-17

Only the two high-frequency severities (roast, observation) get a tunable
knob — the rest fall back to the hardcoded DEFAULT_COOLDOWNS in
unified_notification.py and don't need a UI surface.
"""
import json as _json

from alembic import op
import sqlalchemy as sa


revision = "068_narrator_tunables"
down_revision = "067_narrator_beat"
branch_labels = None
depends_on = None


# (key, display_name, description, category, value_type, default, min, max, unit)
SEED = [
    (
        "notification.cooldown.narrator_roast_hours",
        "Narrator Roast Cooldown",
        "Minimum hours between System AI roast pushes for the same topic. "
        "Lower = more frequent. Per-trigger Redis cooldowns still apply on top.",
        "notifications",
        "float",
        4.0, 0.5, 48.0, "hours",
    ),
    (
        "notification.cooldown.narrator_observation_hours",
        "Narrator Observation Cooldown",
        "Minimum hours between System AI quiet-observation pushes. Observations "
        "are the lowest-stakes severity; the default keeps them rare.",
        "notifications",
        "float",
        8.0, 0.5, 72.0, "hours",
    ),
]


def upgrade():
    bind = op.get_bind()
    for (key, display, desc, cat, vt, default, mn, mx, unit) in SEED:
        bind.execute(
            sa.text(
                """
                INSERT INTO tunable_setting (
                    key, display_name, description, category, value_type,
                    value, default_value, min_value, max_value, unit
                ) VALUES (
                    :key, :display, :desc, :cat, :vt,
                    CAST(:val AS jsonb), CAST(:val AS jsonb),
                    CAST(:mn AS jsonb), CAST(:mx AS jsonb), :unit
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "display": display,
                "desc": desc,
                "cat": cat,
                "vt": vt,
                "val": _json.dumps(default),
                "mn": _json.dumps(mn),
                "mx": _json.dumps(mx),
                "unit": unit,
            },
        )


def downgrade():
    bind = op.get_bind()
    for row in SEED:
        bind.execute(
            sa.text("DELETE FROM tunable_setting WHERE key = :key"),
            {"key": row[0]},
        )
