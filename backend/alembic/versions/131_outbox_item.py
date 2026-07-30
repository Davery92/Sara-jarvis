"""Phase G — unified outbox_item table (work-order item 13, 2026-07-30).

Steps 1-4 of the approved 8-step migration (ARC1_OUTBOX_SCHEMA_PROPOSAL_2026_07_29.md):
1. Create outbox_item (additive superset of autonomy_attention_item + jarvis_inbox).
2. Dual-write via a Postgres trigger on autonomy_attention_item rather than hand-editing
   its 1 INSERT + 14 UPDATE call sites — a trigger can't miss a call site by construction,
   which a code-level dual-write across 6 files genuinely could.
3. Backfill: copy existing autonomy_attention_item rows (254, same id) and jarvis_inbox
   rows (111, mapped kind->category / priority int->varchar / status uppercase->lowercase)
   into outbox_item.
4. Verification is a read-only count/spot-check, done live post-migration, not part of
   the DDL itself.

jarvis_inbox itself is confirmed dead on both ends (no live writer, no live reader — see
proposal doc section 5) so it gets a one-time backfill only, no trigger.

Steps 5 (reader cutover), 6 (notification_log FK rename), 7 (write-freeze + real usage
window), and 8 (drop the old tables) are deliberately NOT in this migration — 7 and 8
need a real event-count usage window David's rider defined (>=50 reads, >=20 writes,
badge parity, zero regressions), which can't be manufactured in one sitting.

Revision ID: 131_outbox_item
Revises: 130_mindv2_deliver
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa


revision = "131_outbox_item"
down_revision = "130_mindv2_deliver"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS outbox_item (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         VARCHAR(255) NOT NULL,
            title           TEXT NOT NULL,
            body            TEXT,
            category        VARCHAR(50) NOT NULL DEFAULT 'general',
            priority        VARCHAR(20) NOT NULL DEFAULT 'normal',
            source          VARCHAR(50) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'new',
            dedupe_key      VARCHAR(255),
            payload         JSONB DEFAULT '{}',
            action_history  JSONB DEFAULT '[]',
            batch_id        VARCHAR(36),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at         TIMESTAMPTZ,
            archived_at     TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ
        )
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_dedupe ON outbox_item (user_id, dedupe_key)
            WHERE dedupe_key IS NOT NULL AND status IN ('new', 'sent')
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_outbox_priority ON outbox_item (user_id, priority, created_at DESC)
            WHERE status IN ('new', 'sent')
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_outbox_user_status ON outbox_item (user_id, status, created_at DESC)
    """))

    # Step 2: dual-write trigger. Fires on every INSERT/UPDATE to autonomy_attention_item
    # regardless of which of its 15 code-level call sites performed it.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION sync_attention_to_outbox() RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO outbox_item (
                id, user_id, title, body, category, priority, source, status,
                dedupe_key, payload, action_history, created_at, updated_at,
                read_at, archived_at, completed_at
            ) VALUES (
                NEW.id, NEW.user_id, NEW.title, NEW.body, NEW.category, NEW.priority,
                NEW.source, NEW.status, NEW.dedupe_key, NEW.payload, NEW.action_history,
                NEW.created_at, NEW.updated_at, NEW.read_at, NEW.archived_at, NEW.completed_at
            )
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                category = EXCLUDED.category,
                priority = EXCLUDED.priority,
                source = EXCLUDED.source,
                status = EXCLUDED.status,
                dedupe_key = EXCLUDED.dedupe_key,
                payload = EXCLUDED.payload,
                action_history = EXCLUDED.action_history,
                updated_at = EXCLUDED.updated_at,
                read_at = EXCLUDED.read_at,
                archived_at = EXCLUDED.archived_at,
                completed_at = EXCLUDED.completed_at;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_attention_to_outbox ON autonomy_attention_item"))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_sync_attention_to_outbox
        AFTER INSERT OR UPDATE ON autonomy_attention_item
        FOR EACH ROW EXECUTE FUNCTION sync_attention_to_outbox()
    """))

    # Step 3a: backfill existing autonomy_attention_item rows (same id, preserves history).
    bind.execute(sa.text("""
        INSERT INTO outbox_item (
            id, user_id, title, body, category, priority, source, status,
            dedupe_key, payload, action_history, created_at, updated_at,
            read_at, archived_at, completed_at
        )
        SELECT
            id, user_id, title, body, category, priority, source, status,
            dedupe_key, payload, action_history, created_at, updated_at,
            read_at, archived_at, completed_at
        FROM autonomy_attention_item
        ON CONFLICT (id) DO NOTHING
    """))

    # Step 3b: backfill jarvis_inbox (dead table, one-time only, no trigger).
    # kind -> category is lowercased 1:1; priority is jarvis_inbox's 1-10 int scale
    # collapsed onto autonomy_attention_item's 4-value varchar scale.
    #
    # Status is forced to 'archived' regardless of jarvis_inbox's own status, NOT
    # lowercased 1:1 like the other fields. jarvis_inbox has confirmed zero live
    # readers (nothing ever queried its status to decide UI behavior) and zero live
    # writers (its two source monitors are themselves unreferenced dead code) — its
    # 'NEW' rows were never shown to David as pending anywhere. compute_badge/
    # build_unified_inbox never read jarvis_inbox before this migration (verified:
    # ARC1_OUTBOX_SCHEMA_PROPOSAL_2026_07_29.md section 5). Backfilling them as live
    # 'new' items into the now-unified outbox_item would resurrect stale historical
    # residue as fresh unread badge count on the first read after cutover — a real
    # regression caught live during step 5 verification (badge went 1 -> 8 on a
    # first pass that lowercased status faithfully). Marking them archived preserves
    # the data (nothing lost) without reviving false urgency nothing ever surfaced.
    bind.execute(sa.text("""
        INSERT INTO outbox_item (
            id, user_id, title, body, category, priority, source, status,
            dedupe_key, payload, action_history, batch_id, created_at,
            updated_at, read_at, archived_at
        )
        SELECT
            id::uuid, user_id, title, body, LOWER(kind::text),
            CASE
                WHEN priority >= 9 THEN 'urgent'
                WHEN priority >= 7 THEN 'high'
                WHEN priority <= 3 THEN 'low'
                ELSE 'normal'
            END,
            COALESCE(source, 'jarvis_inbox'), 'archived',
            dedupe_key, COALESCE(payload, '{}'::jsonb), '[]'::jsonb, batch_id,
            created_at, created_at, read_at, COALESCE(archived_at, created_at)
        FROM jarvis_inbox
        ON CONFLICT (id) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_sync_attention_to_outbox ON autonomy_attention_item"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS sync_attention_to_outbox()"))
    bind.execute(sa.text("DROP TABLE IF EXISTS outbox_item"))
