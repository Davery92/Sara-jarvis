"""M6 — exercise aliases and canonical variant metadata.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 12 / §16 M6.

The problem being solved is PR and progression comparison. `workout_log`
carries legacy text `exercise_id` plus the nullable `exercise_library_id`
shadow FK added in revision 093, and `exercise_pr` identifies a lift by
`exercise_name` — a string. So "Bench Press", "Barbell Bench", "BB Bench"
and "bench press" are four lifts, and "Bench Press" on a Smith machine is
the same lift as a competition bench.

What this adds, and what it deliberately does not:

* `fitness_exercise_alias` — exact, **normalized** alias → canonical id.
  Normalized by `app.schemas.fitness_coach.normalize_code`, the same
  function measurement codes use, so "BB  Bench-Press" and "bb bench press"
  cannot become two keys. Lookup is exact only. A fuzzy match may *suggest*
  candidates to a human; it never rewrites a logged set or merges a PR
  history, because the cost of being wrong is one athlete's record being
  credited to a different movement.
* `load_convention` on `exercise_library` — `total`, `per_hand`, `assisted`,
  `bodyweight`, `stack`. Without it, 40 kg of dumbbell (per hand) and 40 kg
  on a cable stack and 40 kg of pull-up assistance are the same number, and
  summing them as "tonnage" is meaningless.
* `parent_exercise_id` + `variation_code` — barbell and dumbbell bench share
  a movement parent and keep **separate PR histories**. The parent is for
  "how much horizontal pressing", never for a shared record.
* Muscle **roles** (`primary_muscles` / `secondary_muscles`), separate from
  the existing untyped `muscle_groups` JSON, which stays exactly as it is for
  the readers that use it. Direct volume counts primaries; secondary
  involvement is reported separately rather than folded in.

No bulk import, and no reclassification of existing rows. `visibility`
stays `unscoped` from revision 159 until a reviewed classification runs.

Revision ID: 165_fitness_exercise_alias
Revises: 164_fitness_measurements
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "165_fitness_exercise_alias"
down_revision = "164_fitness_measurements"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        ALTER TABLE exercise_library
            ADD COLUMN IF NOT EXISTS parent_exercise_id VARCHAR
                REFERENCES exercise_library(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS variation_code  VARCHAR(60),
            -- How to read a recorded load. 40kg per hand, 40kg on a stack
            -- and 40kg of pull-up assistance are not the same 40kg, and
            -- adding them up as "tonnage" produces a number that means
            -- nothing.
            ADD COLUMN IF NOT EXISTS load_convention VARCHAR(16),
            ADD COLUMN IF NOT EXISTS is_unilateral   BOOLEAN,
            -- Typed muscle ROLES, beside the existing untyped
            -- `muscle_groups` JSON (which is left exactly as it is for the
            -- readers that already use it). Direct volume counts primaries;
            -- secondary involvement is reported separately, never folded in.
            ADD COLUMN IF NOT EXISTS primary_muscles   JSONB,
            ADD COLUMN IF NOT EXISTS secondary_muscles JSONB,
            ADD COLUMN IF NOT EXISTS rom_notes       TEXT,
            ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(200)
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE exercise_library ADD CONSTRAINT ck_exercise_load_convention
                CHECK (load_convention IS NULL OR load_convention IN
                       ('total','per_hand','assisted','bodyweight','stack'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    # A row cannot be its own parent, which a careless variation edit would do
    # and which would make parent traversal loop.
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE exercise_library ADD CONSTRAINT ck_exercise_not_own_parent
                CHECK (parent_exercise_id IS NULL OR parent_exercise_id <> id);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_library_parent
        ON exercise_library (parent_exercise_id)
        WHERE parent_exercise_id IS NOT NULL
    """))

    # `normalized_name` is a plain column, not generated: `normalize_code`
    # lives in Python and its rules (unambiguous abbreviations, punctuation)
    # are not expressible as a stable SQL expression that would survive a
    # change to them. Backfilled below with the SQL equivalent of the current
    # rules and maintained by `services/fitness/exercises.py` on write.
    bind.execute(sa.text("""
        UPDATE exercise_library
        SET normalized_name = TRIM(BOTH '_' FROM
            REGEXP_REPLACE(LOWER(TRIM(name)), '[^a-z0-9]+', '_', 'g'))
        WHERE normalized_name IS NULL
    """))
    # Not unique: two athletes may legitimately have a private exercise with
    # the same name, and revision 159's scope columns are still `unscoped`
    # pending a reviewed classification.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_library_normalized
        ON exercise_library (normalized_name)
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_exercise_alias (
            id                  VARCHAR(36) PRIMARY KEY,
            -- Already normalized when written. Exact lookup only.
            normalized_alias    VARCHAR(200) NOT NULL,
            -- What the athlete actually typed, kept so a suggestion can show
            -- it back to them.
            display_alias       VARCHAR(200),
            exercise_library_id VARCHAR NOT NULL
                                    REFERENCES exercise_library(id) ON DELETE CASCADE,
            -- NULL = a global alias every athlete gets.
            owner_user_id       VARCHAR REFERENCES app_user(id) ON DELETE CASCADE,
            locale              VARCHAR(16) NOT NULL DEFAULT 'en',
            -- 'reviewed' aliases were approved by a human. 'inferred' ones
            -- are suggestions only and are NEVER used for resolution — that
            -- is the whole point of the column.
            review_status       VARCHAR(16) NOT NULL DEFAULT 'reviewed',
            source              VARCHAR(32) NOT NULL DEFAULT 'manual',
            reviewed_by         VARCHAR,
            reviewed_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_exercise_alias_review CHECK (
                review_status IN ('reviewed','inferred','rejected'))
        )
    """))

    # One meaning per alias per scope. A second mapping for the same
    # normalized alias is a genuine ambiguity and must be refused rather than
    # resolved by insertion order.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_exercise_alias_scope
        ON fitness_exercise_alias
           (COALESCE(owner_user_id, ''), locale, normalized_alias)
        WHERE review_status = 'reviewed'
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_alias_lookup
        ON fitness_exercise_alias (normalized_alias, locale)
        WHERE review_status = 'reviewed'
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_alias_target
        ON fitness_exercise_alias (exercise_library_id)
    """))

    # Every existing exercise's own name becomes a reviewed global alias for
    # itself. Safe by construction — it maps a name to the row that already
    # bears it — and it is what makes `resolve_exercise("Bench Press")` work
    # without a separate name-matching code path beside alias lookup.
    #
    # Skips a name that two rows share: that is a real ambiguity, and picking
    # one by insertion order is exactly the silent merge this design refuses.
    bind.execute(sa.text("""
        INSERT INTO fitness_exercise_alias
            (id, normalized_alias, display_alias, exercise_library_id,
             owner_user_id, review_status, source, reviewed_at)
        SELECT gen_random_uuid()::text, e.normalized_name, e.name, e.id,
               NULL, 'reviewed', 'self_name', NOW()
        FROM exercise_library e
        WHERE e.normalized_name IS NOT NULL
          AND e.normalized_name <> ''
          AND NOT EXISTS (
              SELECT 1 FROM fitness_exercise_alias a
              WHERE a.normalized_alias = e.normalized_name
                AND a.owner_user_id IS NULL
                AND a.locale = 'en'
          )
          AND (
              SELECT COUNT(*) FROM exercise_library d
              WHERE d.normalized_name = e.normalized_name
          ) = 1
    """))

    # `exercise_pr` gains a canonical identity beside its legacy text name,
    # plus withdrawal fields. A PR whose source set is later corrected or
    # voided has to be retractable; today there is no column to record that,
    # so the record silently stands on a set that no longer exists.
    bind.execute(sa.text("""
        ALTER TABLE exercise_pr
            ADD COLUMN IF NOT EXISTS exercise_library_id VARCHAR
                REFERENCES exercise_library(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS pr_kind         VARCHAR(24),
            ADD COLUMN IF NOT EXISTS formula_version VARCHAR(24),
            ADD COLUMN IF NOT EXISTS load_unit       VARCHAR(8),
            ADD COLUMN IF NOT EXISTS withdrawn_at    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS withdrawn_reason VARCHAR(200)
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE exercise_pr ADD CONSTRAINT ck_exercise_pr_kind
                CHECK (pr_kind IS NULL OR pr_kind IN
                       ('max_load_for_reps','max_reps_at_load','estimated_1rm'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_pr_canonical
        ON exercise_pr (user_id, exercise_library_id, pr_kind, achieved_at DESC)
        WHERE withdrawn_at IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_pr_source_set
        ON exercise_pr (workout_set_id)
        WHERE workout_set_id IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_exercise_pr_source_set",
        "DROP INDEX IF EXISTS ix_exercise_pr_canonical",
        "ALTER TABLE exercise_pr DROP CONSTRAINT IF EXISTS ck_exercise_pr_kind",
        """ALTER TABLE exercise_pr
               DROP COLUMN IF EXISTS withdrawn_reason,
               DROP COLUMN IF EXISTS withdrawn_at,
               DROP COLUMN IF EXISTS load_unit,
               DROP COLUMN IF EXISTS formula_version,
               DROP COLUMN IF EXISTS pr_kind,
               DROP COLUMN IF EXISTS exercise_library_id""",
        "DROP INDEX IF EXISTS ix_exercise_alias_target",
        "DROP INDEX IF EXISTS ix_exercise_alias_lookup",
        "DROP INDEX IF EXISTS uq_exercise_alias_scope",
        "DROP TABLE IF EXISTS fitness_exercise_alias",
        "DROP INDEX IF EXISTS ix_exercise_library_normalized",
        "DROP INDEX IF EXISTS ix_exercise_library_parent",
        "ALTER TABLE exercise_library DROP CONSTRAINT IF EXISTS ck_exercise_not_own_parent",
        "ALTER TABLE exercise_library DROP CONSTRAINT IF EXISTS ck_exercise_load_convention",
        """ALTER TABLE exercise_library
               DROP COLUMN IF EXISTS normalized_name,
               DROP COLUMN IF EXISTS rom_notes,
               DROP COLUMN IF EXISTS secondary_muscles,
               DROP COLUMN IF EXISTS primary_muscles,
               DROP COLUMN IF EXISTS is_unilateral,
               DROP COLUMN IF EXISTS load_convention,
               DROP COLUMN IF EXISTS variation_code,
               DROP COLUMN IF EXISTS parent_exercise_id""",
    ):
        bind.execute(sa.text(stmt))
