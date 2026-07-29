"""SARA_ALIVE_BUILD_PLAN Arc 1.1/1.3/1.4 — candidate state machine additions
and composed-utterance delivery tracking.

Three pieces, all found/built live during the same session:

1. Arc 1.1 made compose.py advance a candidate to a new `composed` status
   once a composed_utterance row exists for it (previously stuck at
   judged_send forever) — the original ck_say_candidate_status constraint
   (127_mindv2_say_candidate) never allowed it.
2. Arc 1.3 shadow verification found compose has no graceful path for "no
   real payload" (the model would narrate its own non-decision instead of
   staying silent — a voice-contract leak). Added a `declined` terminal
   status, distinct from `composed` (no composed_utterance row exists).
3. Arc 1.4 wires composed_utterance rows to actually deliver through the
   real attention/interruptibility policy instead of staying inspection-
   only forever. Needs delivery tracking (so a row is picked up exactly
   once) and a beat job.

Written idempotently (IF NOT EXISTS / ON CONFLICT DO NOTHING) since the dev
DB already has these applied via one-off scripts run live during the
session (backend/migrations/add_composed_to_say_candidate_status.py,
add_composed_utterance_delivery.py) before this migration was written.

Revision ID: 130_mindv2_deliver
Revises: 129_mindv2_composed_utterance
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "130_mindv2_deliver"
down_revision = "129_mindv2_composed_utterance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("ALTER TABLE say_candidate DROP CONSTRAINT IF EXISTS ck_say_candidate_status"))
    bind.execute(sa.text("""
        ALTER TABLE say_candidate ADD CONSTRAINT ck_say_candidate_status
        CHECK (status IN ('pending', 'judged_send', 'judged_batch', 'judged_drop', 'expired', 'composed', 'declined'))
    """))

    bind.execute(sa.text("""
        ALTER TABLE composed_utterance
        ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS delivery_result JSONB
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_composed_utterance_undelivered
        ON composed_utterance (created_at)
        WHERE delivered_at IS NULL AND review_verdict IN ('approve', 'edit')
    """))

    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, interval_seconds, timezone,
            args, kwargs, queue, expires_seconds, enabled, editable, source, visibility
        ) VALUES (
            'mindv2-deliver-cycle',
            'Mind V2 delivery',
            'Delivers approved/edited composed_utterance rows through the real attention/interruptibility policy (Arc 1.4). Gated by the MINDV2_COMPOSE feature flag.',
            'cognitive',
            'app.tasks.mindv2_deliver.run_delivery_cycle',
            'interval', NULL, 180, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'cognitive', 120, TRUE, TRUE, 'system', 'user'
        ) ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM scheduled_job WHERE key = 'mindv2-deliver-cycle'"))
    op.get_bind().execute(sa.text("DROP INDEX IF EXISTS idx_composed_utterance_undelivered"))
    op.get_bind().execute(sa.text("ALTER TABLE composed_utterance DROP COLUMN IF EXISTS delivery_result"))
    op.get_bind().execute(sa.text("ALTER TABLE composed_utterance DROP COLUMN IF EXISTS delivered_at"))
    op.get_bind().execute(sa.text("ALTER TABLE say_candidate DROP CONSTRAINT IF EXISTS ck_say_candidate_status"))
    op.get_bind().execute(sa.text("""
        ALTER TABLE say_candidate ADD CONSTRAINT ck_say_candidate_status
        CHECK (status IN ('pending','judged_send','judged_batch','judged_drop','expired'))
    """))
