"""Location: place-discovery suggestions + travel-time leave-now nudges.

Revision ID: 081_location_discovery_nudges
Revises: 080_location_awareness
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "081_location_discovery_nudges"
down_revision = "080_location_awareness"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("known_place")}

    if "status" not in cols:
        op.add_column(
            "known_place",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        )
        op.create_index("ix_known_place_status", "known_place", ["status"])

    bind.execute(
        sa.text(
            """
            INSERT INTO scheduled_job (
                key, display_name, description, category, task_name,
                schedule_kind, cron_expr, interval_seconds, timezone,
                args, kwargs, queue, expires_seconds,
                enabled, editable, source, visibility
            ) VALUES
            (
                'location-place-discovery',
                'Place Discovery',
                'Nightly scan of location history for frequently-visited spots not yet saved as places; stages them as suggestions.',
                'location',
                'app.tasks.location.place_discovery',
                'cron', '30 3 * * *', NULL, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 600,
                TRUE, TRUE, 'system', 'system'
            ),
            (
                'location-leave-now-nudges',
                'Leave-Now Travel Nudges',
                'Checks upcoming calendar events with a location against current position and drive time; nudges when it is time to leave.',
                'location',
                'app.tasks.travel_nudge.check_leave_now',
                'interval', NULL, 900, 'America/New_York',
                '[]'::jsonb, '{}'::jsonb, 'cognitive', 300,
                TRUE, TRUE, 'system', 'user'
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM scheduled_job WHERE key IN ('location-place-discovery', 'location-leave-now-nudges')")
    )
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("known_place")}
    if "status" in cols:
        op.drop_index("ix_known_place_status", table_name="known_place")
        op.drop_column("known_place", "status")
