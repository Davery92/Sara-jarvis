"""Belief promotion ladder (§3.3 / D2) — give patterns a door.

Audit finding D2: all 55 behavioral patterns had times_suggested=0 — the mining
is good, but a belief can be born and never become a prediction, a suggestion,
or an automation. Each hop was missing. Phase 2 wired confirmed patterns → the
prediction loop; this adds the ladder status and the standing-order-suggestion
hop, so a confidence-1.0, 33-night pattern can finally become an automation with
David's consent.

Ladder: observed → believed → predictive → actionable → automated.

Revision ID: 114_belief_ladder
Revises: 113_prediction_loop
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "114_belief_ladder"
down_revision = "113_prediction_loop"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "behavioral_pattern",
        sa.Column("ladder_status", sa.String, server_default="observed", nullable=False),
    )
    op.create_index("ix_behavioral_pattern_ladder", "behavioral_pattern", ["ladder_status"])

    bind = op.get_bind()
    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
        ) VALUES (
            'belief-promotion-sweep',
            'Belief promotion sweep',
            'Daily: advance patterns up the ladder (observed→predictive→actionable) and mint standing-order suggestions for confirmed, actionable patterns (§3.3 / D2 door).',
            'cognition',
            'app.tasks.belief_promotion.run_promotion',
            'cron', '0 11 * * *', NULL, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'cognitive', 300, TRUE, TRUE, 'system', 'user'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM scheduled_job WHERE key = 'belief-promotion-sweep'"))
    op.drop_index("ix_behavioral_pattern_ladder", table_name="behavioral_pattern")
    op.drop_column("behavioral_pattern", "ladder_status")
