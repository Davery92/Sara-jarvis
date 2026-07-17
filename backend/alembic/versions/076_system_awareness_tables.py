"""System awareness — Tier 0 subconscious + attention learning tables.

Revision ID: 076_system_awareness_tables
Revises: 075_progress_photos
Create Date: 2026-07-01

THE SYSTEM (Phases 1-3): folds backend/migrations/add_system_awareness_tables.sql
into the alembic chain. That raw SQL file was applied by hand to the live DB on
2026-06-15 (tables already exist there); this revision exists so a fresh deploy
doesn't silently lack them and have tier-0 no-op forever. All statements are
idempotent (CREATE TABLE/INDEX IF NOT EXISTS) so it's a no-op against a DB
where the raw SQL already ran.

See app/services/subconscious.py, app/services/attention_learning.py,
app/routes/system_awareness.py, THE_SYSTEM_DESIGN.md.
"""
from alembic import op


revision = "076_system_awareness_tables"
down_revision = "075_progress_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-(user,domain,signal) rolling baseline -> anomaly detection / habituation.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_baseline (
            id               varchar PRIMARY KEY,
            user_id          varchar NOT NULL,
            domain           varchar NOT NULL,
            signal_key       varchar NOT NULL,
            ewma             double precision,
            ewmvar           double precision,
            last_value       double precision,
            sample_count     bigint DEFAULT 0,
            event_rate_per_hr double precision,
            last_observed_at timestamptz,
            meta             jsonb DEFAULT '{}'::jsonb,
            created_at       timestamptz DEFAULT now(),
            updated_at       timestamptz DEFAULT now(),
            UNIQUE (user_id, domain, signal_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_signal_baseline_user_domain "
        "ON signal_baseline (user_id, domain)"
    )

    # Attribution log: every subconscious->conscious promotion + its engagement
    # outcome. This is the learning training data.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS promotion_event (
            id                 varchar PRIMARY KEY,
            user_id            varchar NOT NULL,
            created_at         timestamptz DEFAULT now(),
            domain             varchar NOT NULL,
            context            varchar NOT NULL,
            signal_key         varchar,
            signal_ref         varchar,
            significance       double precision,
            threshold_at_time  double precision,
            reason             varchar,
            promoted           boolean DEFAULT false,
            surfaced_as        varchar,
            notification_id    varchar,
            description        text,
            outcome            varchar,
            outcome_at         timestamptz,
            engaged            boolean,
            meta               jsonb DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promotion_event_user_created "
        "ON promotion_event (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promotion_event_domain_context "
        "ON promotion_event (user_id, domain, context)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promotion_event_notif "
        "ON promotion_event (notification_id)"
    )

    # Learned promotion policy per (user, domain, context). Partial-pooling via domain_prior.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attention_policy (
            id            varchar PRIMARY KEY,
            user_id       varchar NOT NULL,
            domain        varchar NOT NULL,
            context       varchar NOT NULL,
            threshold     double precision NOT NULL DEFAULT 0.5,
            domain_prior  double precision NOT NULL DEFAULT 0.5,
            explore_rate  double precision NOT NULL DEFAULT 0.1,
            anomaly_floor double precision NOT NULL DEFAULT 0.85,
            surface_budget integer,
            n_surfaced    bigint DEFAULT 0,
            n_engaged     bigint DEFAULT 0,
            n_ignored     bigint DEFAULT 0,
            n_dismissed   bigint DEFAULT 0,
            last_updated  timestamptz DEFAULT now(),
            created_at    timestamptz DEFAULT now(),
            UNIQUE (user_id, domain, context)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_attention_policy_user "
        "ON attention_policy (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attention_policy_user")
    op.execute("DROP TABLE IF EXISTS attention_policy")
    op.execute("DROP INDEX IF EXISTS ix_promotion_event_notif")
    op.execute("DROP INDEX IF EXISTS ix_promotion_event_domain_context")
    op.execute("DROP INDEX IF EXISTS ix_promotion_event_user_created")
    op.execute("DROP TABLE IF EXISTS promotion_event")
    op.execute("DROP INDEX IF EXISTS ix_signal_baseline_user_domain")
    op.execute("DROP TABLE IF EXISTS signal_baseline")
