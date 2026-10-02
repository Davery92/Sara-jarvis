"""M9 — the coach review and recommendation audit trail.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 19 / §5.5 / §16 M9.

This is the table that makes "why did you tell me to cut calories?"
answerable three months later. The shape is chosen so that it cannot answer
it *approximately*:

* **The input snapshot is immutable once the review completes.** A
  `BEFORE UPDATE` trigger refuses to change `input_state`, `input_hash`,
  `period_start`, `period_end` or any version column on a row whose status
  is terminal. Without that, "here are the numbers I reasoned from" is only
  a claim about the current contents of a mutable column.
* **Idempotency is a real unique index**, on
  `(user_id, kind, period_start, period_end, input_hash, prompt_version)`.
  A retried request returns the same run rather than paying for a second
  model call and producing a second, differently-worded answer to one
  question.
* **A rerun after corrected data is a LINKED REVISION, not an overwrite.**
  `supersedes_id` plus a partial unique index on
  `(user_id, kind, period_start, period_end) WHERE superseded_by_id IS NULL`
  means one current review per period with the whole chain retained. The old
  review said what it said on the data it had; deleting it would destroy the
  only record of why a decision was made.
* **A recommendation is a PROPOSAL.** There is no column on this table that
  changes a target, and `decision_status` defaults to `pending`. The applied
  change, when it happens, is a `fitness_target_revision` row that points
  back here through `review_recommendation_id` — which already exists from
  M3. A CHECK constraint requires an `action_receipt` id before a row may
  claim it was accepted, so "applied" cannot be asserted without the durable
  receipt that proves an execution happened.
* **Failures record a CATEGORY, not a prompt.** `error_category` is a short
  enumerated string and `error_detail` is capped; the prompt text and the
  raw model transcript are deliberately not stored. A failed review that
  banked the full prompt would make this table the largest copy of the
  athlete's private data in the database, kept for the least useful reason.

What is deliberately NOT here: raw multi-month history, the full prompt, the
model's unvalidated text. `input_state` is a compact `FitnessStateV1` — the
same projection the UI reads — with its schema and analytics versions beside
it, so a reader three months from now knows which arithmetic produced it.

Revision ID: 168_fitness_review_audit
Revises: 167_fitness_pain
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "168_fitness_review_audit"
down_revision = "167_fitness_pain"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ── fitness_coach_review ───────────────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_coach_review (
            id                  VARCHAR(36) PRIMARY KEY,
            user_id             VARCHAR NOT NULL
                                    REFERENCES app_user(id) ON DELETE CASCADE,

            kind                VARCHAR(32) NOT NULL,

            -- Half-open athlete-local interval. `period_end` EXCLUSIVE, like
            -- every other window in this subsystem, so a review of "last
            -- week" never silently includes a partial current day.
            period_start        DATE NOT NULL,
            period_end          DATE NOT NULL,

            status              VARCHAR(20) NOT NULL DEFAULT 'pending',

            -- The compact FitnessStateV1 this review reasoned from, and the
            -- fingerprint of it. The hash is what idempotency is keyed on:
            -- the same question over the same data is one run.
            input_state         JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_hash          VARCHAR(64) NOT NULL,

            -- Which arithmetic and which projection shape produced that
            -- state. Three months on, "mean_7d" may mean something else;
            -- these say which version's meaning applies.
            state_schema_version    INTEGER NOT NULL,
            analytics_version       INTEGER NOT NULL,

            -- The data the state was built from, at the moment of
            -- collection. If a later correction changes this, the review is
            -- stale and a rerun produces a linked revision.
            data_revision       VARCHAR(64),
            collected_at        TIMESTAMPTZ NOT NULL,
            source_cutoff       TIMESTAMPTZ,

            -- The ACTUAL model that answered, not the one that was asked
            -- for. A fallback that silently answered as the primary makes
            -- every later comparison between runs meaningless.
            model_requested     VARCHAR(120),
            model_actual        VARCHAR(120),
            provider            VARCHAR(60),
            prompt_version      VARCHAR(40) NOT NULL,
            prompt_hash         VARCHAR(64),
            output_schema_version INTEGER,

            -- Validated output only. An unvalidated blob here would be read
            -- as the coach's conclusion by everything downstream.
            output              JSONB,
            summary             TEXT,
            evidence_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- A category, never a prompt. See the module docstring.
            error_category      VARCHAR(40),
            error_detail        VARCHAR(500),

            run_id              VARCHAR(64),
            attempt             INTEGER NOT NULL DEFAULT 1,

            -- The revision chain. A rerun after corrected data links, never
            -- overwrites.
            -- DEFERRABLE, and it has to be. `uq_coach_review_current` is a
            -- partial unique index, which PostgreSQL checks at every
            -- statement rather than at commit, so a successor cannot be
            -- inserted while its predecessor is still unlinked. The writer
            -- therefore links the OLD row to the new id first and inserts
            -- the new row second — which needs the FK checked at commit.
            -- A partial unique index cannot itself be deferred, so this is
            -- the end that moves.
            supersedes_id       VARCHAR(36)
                REFERENCES fitness_coach_review(id) ON DELETE SET NULL
                DEFERRABLE INITIALLY DEFERRED,
            superseded_by_id    VARCHAR(36)
                REFERENCES fitness_coach_review(id) ON DELETE SET NULL
                DEFERRABLE INITIALLY DEFERRED,
            revision            INTEGER NOT NULL DEFAULT 1,

            requested_by        VARCHAR(20) NOT NULL DEFAULT 'schedule',
            evaluated_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_coach_review_period
                CHECK (period_end > period_start),
            CONSTRAINT ck_coach_review_status
                CHECK (status IN (
                    'pending', 'running', 'complete', 'failed', 'insufficient_data'
                )),
            CONSTRAINT ck_coach_review_kind
                CHECK (kind IN (
                    'weekly', 'biweekly', 'monthly', 'on_demand',
                    'phase_transition', 'photo_comparison'
                )),
            CONSTRAINT ck_coach_review_requested_by
                CHECK (requested_by IN ('schedule', 'user', 'system')),
            -- A complete review has an output. A failed one has a reason.
            -- Neither may be silent about which it is: a 'complete' row with
            -- no output would be read as "the coach had nothing to say".
            CONSTRAINT ck_coach_review_complete_has_output
                CHECK (status <> 'complete' OR output IS NOT NULL),
            CONSTRAINT ck_coach_review_failed_has_reason
                CHECK (status <> 'failed' OR error_category IS NOT NULL),
            -- A row cannot supersede itself.
            CONSTRAINT ck_coach_review_not_self_superseding
                CHECK (supersedes_id IS NULL OR supersedes_id <> id),
            CONSTRAINT ck_coach_review_attempt CHECK (attempt >= 1),
            CONSTRAINT ck_coach_review_revision CHECK (revision >= 1)
        )
    """))

    # Idempotency. The same question over the same data, with the same
    # prompt, is ONE run — a retry after a timeout must return the existing
    # row rather than pay for a second model call and produce a second,
    # differently worded answer to one question.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_coach_review_idempotency
        ON fitness_coach_review
           (user_id, kind, period_start, period_end, input_hash, prompt_version)
    """))

    # One CURRENT review per period and kind. The superseded ones stay, which
    # is the whole point of the chain.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_coach_review_current
        ON fitness_coach_review (user_id, kind, period_start, period_end)
        WHERE superseded_by_id IS NULL
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coach_review_user_period
        ON fitness_coach_review (user_id, period_end DESC, kind)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coach_review_status
        ON fitness_coach_review (user_id, status)
        WHERE status IN ('pending', 'running')
    """))

    # ── Immutability of a completed review's inputs ───────────────────────
    #
    # A trigger, not a convention. "The snapshot is immutable" enforced only
    # by code that remembers to not write it is not an audit trail — it is a
    # mutable column with a comment, and the first bulk UPDATE proves it.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_coach_review_freeze()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status IN ('complete', 'failed', 'insufficient_data') THEN
                IF NEW.input_state      IS DISTINCT FROM OLD.input_state
                OR NEW.input_hash       IS DISTINCT FROM OLD.input_hash
                OR NEW.period_start     IS DISTINCT FROM OLD.period_start
                OR NEW.period_end       IS DISTINCT FROM OLD.period_end
                OR NEW.kind             IS DISTINCT FROM OLD.kind
                OR NEW.user_id          IS DISTINCT FROM OLD.user_id
                OR NEW.state_schema_version IS DISTINCT FROM OLD.state_schema_version
                OR NEW.analytics_version    IS DISTINCT FROM OLD.analytics_version
                OR NEW.data_revision    IS DISTINCT FROM OLD.data_revision
                OR NEW.collected_at     IS DISTINCT FROM OLD.collected_at
                OR NEW.model_actual     IS DISTINCT FROM OLD.model_actual
                OR NEW.prompt_version   IS DISTINCT FROM OLD.prompt_version
                OR NEW.prompt_hash      IS DISTINCT FROM OLD.prompt_hash
                OR NEW.output           IS DISTINCT FROM OLD.output
                THEN
                    RAISE EXCEPTION
                        'fitness_coach_review % is terminal (%); its inputs and '
                        'output are immutable. Record a new review that '
                        'supersedes it instead.',
                        OLD.id, OLD.status
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_fitness_coach_review_freeze
        ON fitness_coach_review
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_fitness_coach_review_freeze
        BEFORE UPDATE ON fitness_coach_review
        FOR EACH ROW EXECUTE FUNCTION fitness_coach_review_freeze()
    """))

    # ── fitness_coach_recommendation ──────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_coach_recommendation (
            id                  VARCHAR(36) PRIMARY KEY,
            review_id           VARCHAR(36) NOT NULL
                REFERENCES fitness_coach_review(id) ON DELETE CASCADE,
            -- Denormalized deliberately: every query here is owner-scoped,
            -- and joining to the review to find the owner means a missed
            -- join is an authorization hole rather than a slow query.
            user_id             VARCHAR NOT NULL
                REFERENCES app_user(id) ON DELETE CASCADE,

            category            VARCHAR(40) NOT NULL,
            -- The PROPOSAL kind, from `ProposedChangeKind`.
            action              VARCHAR(40) NOT NULL DEFAULT 'none',
            title               VARCHAR(200) NOT NULL,
            rationale           TEXT NOT NULL,

            -- Model interpretation, kept separate from data coverage (§9.6).
            -- A review can be very confident about a conclusion drawn from
            -- two days of data, and be wrong for exactly that reason.
            confidence          VARCHAR(12) NOT NULL DEFAULT 'low',
            confidence_basis    TEXT,
            limitations         TEXT,

            -- Exactly which state metrics were cited, so an invented metric
            -- reference is caught rather than rendered.
            metric_paths        JSONB NOT NULL DEFAULT '[]'::jsonb,
            evidence_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- The typed PROPOSAL. Nothing reads this as applied state.
            proposed_change     JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- What it was proposed against, so a stale proposal is
            -- detectable rather than silently applied over a newer target.
            current_target_revision_id VARCHAR(36)
                REFERENCES fitness_target_revision(id) ON DELETE SET NULL,
            current_phase_id    VARCHAR
                REFERENCES fitness_phase(id) ON DELETE SET NULL,

            expires_at          TIMESTAMPTZ,

            decision_status     VARCHAR(16) NOT NULL DEFAULT 'proposed',
            decided_at          TIMESTAMPTZ,
            decided_by          VARCHAR(20),
            decision_note       TEXT,

            -- The durable proof that something executed. A recommendation
            -- may not claim it was applied without one.
            action_receipt_id   VARCHAR(36),
            -- The revision this proposal actually produced, when accepted.
            applied_revision_id VARCHAR(36)
                REFERENCES fitness_target_revision(id) ON DELETE SET NULL,

            priority            INTEGER NOT NULL DEFAULT 5,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_coach_rec_confidence
                CHECK (confidence IN ('low', 'moderate', 'high')),
            -- 'proposed', matching `DecisionStatus` in
            -- `app/schemas/fitness_coach.py`. Two vocabularies for one
            -- concept is the drift this subsystem keeps closing; the schema
            -- was written first, so the column follows it.
            CONSTRAINT ck_coach_rec_decision
                CHECK (decision_status IN (
                    'proposed', 'accepted', 'rejected', 'expired', 'superseded'
                )),
            CONSTRAINT ck_coach_rec_decided_by
                CHECK (decided_by IS NULL
                       OR decided_by IN ('user', 'system', 'expiry')),
            CONSTRAINT ck_coach_rec_priority
                CHECK (priority BETWEEN 1 AND 10),
            -- A decision has a time. "Accepted at some point" is not an
            -- audit trail.
            CONSTRAINT ck_coach_rec_decided_has_time
                CHECK (decision_status = 'proposed' OR decided_at IS NOT NULL),
            -- The one that keeps a proposal from masquerading as a change:
            -- claiming 'accepted' requires the receipt that proves an
            -- execution happened. A prompt rule cannot stop a model from
            -- saying it did something; this can.
            CONSTRAINT ck_coach_rec_accepted_needs_receipt
                CHECK (decision_status <> 'accepted'
                       OR action_receipt_id IS NOT NULL
                       OR applied_revision_id IS NOT NULL),
            -- And nothing that is NOT accepted may carry either.
            CONSTRAINT ck_coach_rec_unaccepted_has_no_effect
                CHECK (decision_status = 'accepted'
                       OR (action_receipt_id IS NULL
                           AND applied_revision_id IS NULL)),
            -- Exactly `RecommendationCategory`. A closed set: a value
            -- outside it is a rejected model output, not a new category,
            -- and a free-text column here would let one through.
            CONSTRAINT ck_coach_rec_category
                CHECK (category IN (
                    'maintain', 'progress', 'reduce', 'exercise_change',
                    'volume_change', 'nutrition_change',
                    'prioritize_recovery', 'request_data', 'flag_concern'
                )),
            -- Exactly `ProposedChangeKind`. `none` is the common case and
            -- is a real answer: "keep going" is advice, not an absence of
            -- advice, and it must be storable without a proposed change.
            CONSTRAINT ck_coach_rec_action
                CHECK (action IN (
                    'none', 'target_revision', 'data_request', 'program_change'
                ))
        )
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coach_rec_user_status
        ON fitness_coach_recommendation (user_id, decision_status, created_at DESC)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coach_rec_review
        ON fitness_coach_recommendation (review_id)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coach_rec_open
        ON fitness_coach_recommendation (user_id, expires_at)
        WHERE decision_status = 'proposed'
    """))

    # Ownership is enforced, not assumed. §5: "an FK to a UUID alone does not
    # enforce ownership." Without this a recommendation could hang off
    # another athlete's review and be served under this athlete's auth.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_coach_rec_same_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            review_owner VARCHAR;
        BEGIN
            SELECT user_id INTO review_owner
            FROM fitness_coach_review WHERE id = NEW.review_id;
            IF review_owner IS NULL THEN
                RAISE EXCEPTION 'review % does not exist', NEW.review_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF review_owner <> NEW.user_id THEN
                RAISE EXCEPTION
                    'recommendation owner % does not match review owner %',
                    NEW.user_id, review_owner
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_fitness_coach_rec_same_owner
        ON fitness_coach_recommendation
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_fitness_coach_rec_same_owner
        BEFORE INSERT OR UPDATE ON fitness_coach_recommendation
        FOR EACH ROW EXECUTE FUNCTION fitness_coach_rec_same_owner()
    """))

    # The same ownership rule for a review's supersession chain: a revision
    # of someone else's review would put their numbers in this athlete's
    # audit trail.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_coach_review_chain_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            other_owner VARCHAR;
        BEGIN
            IF NEW.supersedes_id IS NOT NULL THEN
                SELECT user_id INTO other_owner
                FROM fitness_coach_review WHERE id = NEW.supersedes_id;
                IF other_owner IS NOT NULL AND other_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'review % cannot supersede another athlete''s review',
                        NEW.id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_fitness_coach_review_chain_owner
        ON fitness_coach_review
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_fitness_coach_review_chain_owner
        BEFORE INSERT OR UPDATE ON fitness_coach_review
        FOR EACH ROW EXECUTE FUNCTION fitness_coach_review_chain_owner()
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP TRIGGER IF EXISTS trg_fitness_coach_review_chain_owner ON fitness_coach_review",
        "DROP FUNCTION IF EXISTS fitness_coach_review_chain_owner()",
        "DROP TRIGGER IF EXISTS trg_fitness_coach_rec_same_owner ON fitness_coach_recommendation",
        "DROP FUNCTION IF EXISTS fitness_coach_rec_same_owner()",
        "DROP INDEX IF EXISTS ix_coach_rec_open",
        "DROP INDEX IF EXISTS ix_coach_rec_review",
        "DROP INDEX IF EXISTS ix_coach_rec_user_status",
        "DROP TABLE IF EXISTS fitness_coach_recommendation",
        "DROP TRIGGER IF EXISTS trg_fitness_coach_review_freeze ON fitness_coach_review",
        "DROP FUNCTION IF EXISTS fitness_coach_review_freeze()",
        "DROP INDEX IF EXISTS ix_coach_review_status",
        "DROP INDEX IF EXISTS ix_coach_review_user_period",
        "DROP INDEX IF EXISTS uq_coach_review_current",
        "DROP INDEX IF EXISTS uq_coach_review_idempotency",
        "DROP TABLE IF EXISTS fitness_coach_review",
    ):
        bind.execute(sa.text(stmt))
