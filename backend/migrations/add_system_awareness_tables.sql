-- THE SYSTEM — Tier 0 (subconscious) + learning loop tables.
-- Idempotent. Run: docker exec -i jarvis-db-1 psql -U sara -d sara_hub < this.sql

-- Per-(user,domain,signal) rolling baseline → anomaly detection / habituation.
CREATE TABLE IF NOT EXISTS signal_baseline (
    id               varchar PRIMARY KEY,
    user_id          varchar NOT NULL,
    domain           varchar NOT NULL,
    signal_key       varchar NOT NULL,        -- e.g. 'resting_hr', 'hrv', 'home.light'
    ewma             double precision,         -- current EWMA (numeric signals)
    ewmvar           double precision,         -- EWMA variance
    last_value       double precision,
    sample_count     bigint DEFAULT 0,
    event_rate_per_hr double precision,        -- for event-type signals (home)
    last_observed_at timestamptz,
    meta             jsonb DEFAULT '{}'::jsonb,
    created_at       timestamptz DEFAULT now(),
    updated_at       timestamptz DEFAULT now(),
    UNIQUE (user_id, domain, signal_key)
);
CREATE INDEX IF NOT EXISTS ix_signal_baseline_user_domain ON signal_baseline (user_id, domain);

-- Attribution log: every subconscious→conscious promotion + its engagement outcome.
-- THIS IS THE LEARNING TRAINING DATA.
CREATE TABLE IF NOT EXISTS promotion_event (
    id                 varchar PRIMARY KEY,
    user_id            varchar NOT NULL,
    created_at         timestamptz DEFAULT now(),
    domain             varchar NOT NULL,
    context            varchar NOT NULL,        -- focused|available|away|winding_down|asleep
    signal_key         varchar,
    signal_ref         varchar,                 -- pointer to source row/observation
    significance       double precision,
    threshold_at_time  double precision,
    reason             varchar,                 -- anomaly|relevance|exploration|override|baseline
    promoted           boolean DEFAULT false,   -- did it cross to conscious
    surfaced_as        varchar,                 -- notification|deliberation|none
    notification_id    varchar,
    description        text,
    outcome            varchar,                 -- engaged|read|ignored|dismissed|stop
    outcome_at         timestamptz,
    engaged            boolean,
    meta               jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_promotion_event_user_created ON promotion_event (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_promotion_event_domain_context ON promotion_event (user_id, domain, context);
CREATE INDEX IF NOT EXISTS ix_promotion_event_notif ON promotion_event (notification_id);

-- Learned promotion policy per (user, domain, context). Partial-pooling via domain_prior.
CREATE TABLE IF NOT EXISTS attention_policy (
    id            varchar PRIMARY KEY,
    user_id       varchar NOT NULL,
    domain        varchar NOT NULL,
    context       varchar NOT NULL,
    threshold     double precision NOT NULL DEFAULT 0.5,   -- θ
    domain_prior  double precision NOT NULL DEFAULT 0.5,   -- shared prior across contexts
    explore_rate  double precision NOT NULL DEFAULT 0.1,   -- ε exploration floor
    anomaly_floor double precision NOT NULL DEFAULT 0.85,  -- significance that always promotes
    surface_budget integer,                                -- soft daily cap (nullable)
    n_surfaced    bigint DEFAULT 0,
    n_engaged     bigint DEFAULT 0,
    n_ignored     bigint DEFAULT 0,
    n_dismissed   bigint DEFAULT 0,
    last_updated  timestamptz DEFAULT now(),
    created_at    timestamptz DEFAULT now(),
    UNIQUE (user_id, domain, context)
);
CREATE INDEX IF NOT EXISTS ix_attention_policy_user ON attention_policy (user_id);
