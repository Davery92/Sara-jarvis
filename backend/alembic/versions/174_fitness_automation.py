"""M15 — approved automation policies, with bounds that mean something.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 30 / §16 M15.

This is the step where the coach may act without asking. The schema's whole
job is keeping that permission narrow enough to be worth having.

What it makes impossible:

* **A permission with no end.** `expires_at` is NOT NULL. A policy nobody
  remembers granting is one nobody can reason about, and an automation that
  outlives the situation it was approved for is the failure mode.
* **A size limit with no frequency limit.** Both `max_change` and
  `max_actions_per_window` are NOT NULL. Fourteen approved 50-calorie steps
  is a 700-calorie change nobody approved.
* **One permission covering several kinds of act.** A policy names exactly
  one `action`, and a partial unique index allows one live policy per
  action per athlete. §30.2: the existing in-workout rest approvals do not
  authorize a calorie or program change, and there is no row shape here
  that could express "all of it".
* **An automation enabled by default.** `enabled` defaults to FALSE and a
  policy has to carry `approved_by`. Nothing is on until somebody turned
  it on.
* **An action with no receipt.** `fitness_automation_action` has a unique
  `idempotency_key` and a CHECK requiring a receipt id on an applied row —
  so a change that executed always has a durable row `verify_action` can
  read back, and a retry cannot apply twice.
* **Rewriting what an automation did.** Applied and denied rows are frozen
  by a trigger. The log is the record of what was done under a permission;
  a mutable one is a cache.

Revision ID: 174_fitness_automation
Revises: 173_fitness_program_ver
"""
from alembic import op

revision = "174_fitness_automation"
down_revision = "173_fitness_program_ver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_automation_policy (
            id                    VARCHAR PRIMARY KEY,
            user_id               VARCHAR NOT NULL
                                  REFERENCES app_user(id) ON DELETE CASCADE,
            action                VARCHAR(40) NOT NULL,
            -- FALSE by default: nothing is automated until somebody turns
            -- it on, and a migration that enabled anything would be
            -- granting a permission on the athlete's behalf.
            enabled               BOOLEAN NOT NULL DEFAULT FALSE,
            max_change            NUMERIC(10, 3) NOT NULL,
            min_change            NUMERIC(10, 3) NOT NULL DEFAULT 0,
            max_actions_per_window INTEGER NOT NULL,
            window_days           INTEGER NOT NULL,
            min_coverage_days     INTEGER NOT NULL,
            coverage_window_days  INTEGER NOT NULL,
            requires_evidence     BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at            TIMESTAMPTZ NOT NULL,
            notify                BOOLEAN NOT NULL DEFAULT TRUE,
            note                  TEXT,
            policy_version        INTEGER NOT NULL DEFAULT 1,
            approved_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            approved_by           VARCHAR NOT NULL,
            revoked_at            TIMESTAMPTZ,
            revoked_reason        TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_automation_action CHECK (action IN (
                'calorie_adjust', 'macro_adjust', 'scheduled_deload',
                'progression_apply', 'pain_load_reduction'
            )),
            CONSTRAINT ck_automation_bounds CHECK (
                max_change > 0 AND min_change >= 0
                AND min_change < max_change
            ),
            CONSTRAINT ck_automation_rate CHECK (
                max_actions_per_window >= 1 AND max_actions_per_window <= 30
                AND window_days >= 1 AND window_days <= 365
            ),
            CONSTRAINT ck_automation_coverage CHECK (
                min_coverage_days >= 1
                AND coverage_window_days >= min_coverage_days
                AND coverage_window_days <= 365
            ),
            -- A policy approved by a model is not an approval. The same
            -- rule as a program draft's acceptance, for the same reason.
            CONSTRAINT ck_automation_approved_by CHECK (
                approved_by NOT IN ('model', 'llm', 'autonomous', 'system')
            ),
            CONSTRAINT ck_automation_revoked CHECK (
                revoked_at IS NULL OR revoked_reason IS NOT NULL
            )
        )
    """)
    # One live policy per action per athlete. Two would mean two answers to
    # "what did I agree to", and whichever the code read first would win.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_automation_policy_live
        ON fitness_automation_policy (user_id, action)
        WHERE revoked_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_automation_policy_owner
        ON fitness_automation_policy (user_id, action, enabled)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_automation_action (
            id              VARCHAR PRIMARY KEY,
            user_id         VARCHAR NOT NULL
                            REFERENCES app_user(id) ON DELETE CASCADE,
            policy_id       VARCHAR
                            REFERENCES fitness_automation_policy(id)
                            ON DELETE SET NULL,
            action          VARCHAR(40) NOT NULL,
            decision        VARCHAR(20) NOT NULL,
            denial          VARCHAR(40),
            reason          TEXT NOT NULL,
            applied_change  NUMERIC(10, 3),
            -- The durable row `verify_action` reads back. An applied
            -- action without one is a claim.
            receipt_id      VARCHAR,
            -- Set when the attempt became a proposal instead of an action.
            recommendation_id VARCHAR,
            -- What the policy looked like at decision time. A policy can be
            -- edited, and "what were the bounds when this fired" has to
            -- survive that.
            policy_snapshot JSONB,
            -- Which program/target revision it acted against, so a stale
            -- action is identifiable after the fact.
            target_revision_id VARCHAR,
            program_revision   INTEGER,
            coverage_days   INTEGER,
            idempotency_key VARCHAR(200) NOT NULL,
            notified        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_automation_action_kind CHECK (action IN (
                'calorie_adjust', 'macro_adjust', 'scheduled_deload',
                'progression_apply', 'pain_load_reduction'
            )),
            CONSTRAINT ck_automation_decision CHECK (decision IN (
                'applied', 'applied_notified', 'proposed', 'denied'
            )),
            -- An applied action carries its receipt and its size.
            CONSTRAINT ck_automation_applied_has_receipt CHECK (
                decision NOT IN ('applied', 'applied_notified')
                OR (receipt_id IS NOT NULL AND applied_change IS NOT NULL
                    AND policy_id IS NOT NULL)
            ),
            -- A denial names the guard that stopped it. "No" with no
            -- reason is indistinguishable from a bug.
            CONSTRAINT ck_automation_denied_has_denial CHECK (
                decision <> 'denied' OR denial IS NOT NULL
            ),
            CONSTRAINT ck_automation_change_only_when_applied CHECK (
                decision IN ('applied', 'applied_notified')
                OR applied_change IS NULL
            )
        )
    """)
    # The idempotency key is the real guard against a retry applying twice:
    # a worker that loses its connection after the UPDATE and before its
    # own bookkeeping retries the whole attempt.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_automation_action_idem
        ON fitness_automation_action (user_id, idempotency_key)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_automation_action_window
        ON fitness_automation_action (user_id, action, created_at DESC)
        WHERE decision IN ('applied', 'applied_notified')
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_automation_action_recent
        ON fitness_automation_action (user_id, created_at DESC)
    """)

    # ── An action row is a record, not a cache ─────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_automation_action_frozen()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.decision IS DISTINCT FROM OLD.decision
               OR NEW.applied_change IS DISTINCT FROM OLD.applied_change
               OR NEW.receipt_id IS DISTINCT FROM OLD.receipt_id
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR NEW.denial IS DISTINCT FROM OLD.denial
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.policy_snapshot::text
                  IS DISTINCT FROM OLD.policy_snapshot::text THEN
                RAISE EXCEPTION
                    'automation action % is a record of what was done under '
                    'a permission; it cannot be rewritten. Only `notified` '
                    'may change.', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_automation_action_frozen
            ON fitness_automation_action;
        CREATE TRIGGER trg_automation_action_frozen
        BEFORE UPDATE ON fitness_automation_action
        FOR EACH ROW EXECUTE FUNCTION fitness_automation_action_frozen()
    """)

    # ── An action's policy authorizes that action ──────────────────────
    # §30.2's central rule, as a constraint: approving rest automation has
    # never authorized a calorie change, and this is what makes an
    # implementation that confused them fail loudly.
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_automation_action_matches_policy()
        RETURNS TRIGGER AS $$
        DECLARE
            policy_action VARCHAR;
            policy_owner VARCHAR;
        BEGIN
            IF NEW.policy_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT action, user_id INTO policy_action, policy_owner
            FROM fitness_automation_policy WHERE id = NEW.policy_id;
            IF policy_owner IS DISTINCT FROM NEW.user_id THEN
                RAISE EXCEPTION
                    'automation action owner % does not match policy owner %',
                    NEW.user_id, policy_owner;
            END IF;
            IF policy_action IS DISTINCT FROM NEW.action THEN
                RAISE EXCEPTION
                    'a % policy does not authorize a % action — a permission '
                    'is for one kind of act',
                    policy_action, NEW.action;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_automation_action_policy
            ON fitness_automation_action;
        CREATE TRIGGER trg_automation_action_policy
        BEFORE INSERT OR UPDATE ON fitness_automation_action
        FOR EACH ROW
        EXECUTE FUNCTION fitness_automation_action_matches_policy()
    """)

    # ── Source adapters (§30.4) ────────────────────────────────────────
    # Registered, not hard-coded, and narrow: a row says which metrics a
    # source may write, which timestamp convention its data uses, and
    # whether it may overwrite. The three timestamp conventions in this
    # database are why the column exists — a source that does not declare
    # one lands its data 4-5 hours out.
    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_source_adapter (
            id                   VARCHAR PRIMARY KEY,
            user_id              VARCHAR
                                 REFERENCES app_user(id) ON DELETE CASCADE,
            kind                 VARCHAR(30) NOT NULL,
            vendor               VARCHAR(80) NOT NULL,
            external_id_field    VARCHAR(80) NOT NULL,
            writes_metrics       JSONB NOT NULL,
            timestamp_convention VARCHAR(20) NOT NULL,
            requires_consent     BOOLEAN NOT NULL DEFAULT TRUE,
            may_overwrite        BOOLEAN NOT NULL DEFAULT FALSE,
            consented_at         TIMESTAMPTZ,
            enabled              BOOLEAN NOT NULL DEFAULT FALSE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_source_kind CHECK (kind IN (
                'healthkit', 'manual', 'scale', 'nutrition_api', 'wearable'
            )),
            CONSTRAINT ck_source_timestamp CHECK (
                timestamp_convention IN ('aware_utc', 'naive_utc',
                                         'naive_local')
            ),
            CONSTRAINT ck_source_metrics CHECK (
                jsonb_typeof(writes_metrics) = 'array'
                AND jsonb_array_length(writes_metrics) > 0
            ),
            -- A consenting source that is enabled has consent on file.
            CONSTRAINT ck_source_consent CHECK (
                enabled = FALSE OR requires_consent = FALSE
                OR consented_at IS NOT NULL
            )
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_source_adapter
        ON fitness_source_adapter (COALESCE(user_id, ''), kind, vendor)
    """)


def downgrade() -> None:
    """Drops the policies and the action log.

    Note what this destroys: the record of what the coach did under which
    permission. The changes themselves are in `fitness_target_revision` and
    the receipts; what is lost is the authorization trail. §7: never run a
    downgrade as a recovery step.
    """
    for table in ("fitness_automation_action", "fitness_automation_policy",
                  "fitness_source_adapter"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute(
        "DROP FUNCTION IF EXISTS fitness_automation_action_frozen()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS fitness_automation_action_matches_policy()"
    )
