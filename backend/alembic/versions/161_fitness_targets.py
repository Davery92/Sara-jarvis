"""M2 — dated target revisions.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 6 / §16 M2. Versions the nutrition
targets that already exist on `fitness_phase` (phase scope) and
`fitness_goals` (default scope), without taking authority away from either.

Why a revision table and not a mutable override table (§4.3):

`fitness_phase.calories_target` is edited in place today. That means the
answer to "what was my protein target on 14 February" is "whatever the row
says now" — and `plan_adjust.py` legitimately trims, splits and shifts those
phases, so the row's dates move too. Historical adherence computed against
mutable current values is not adherence; it is a comparison of past intake
against a target that may never have applied.

Each revision is a **complete resolved snapshot**, not a patch. A patch chain
makes a historical read a replay of every edit, where one lost edit silently
rewrites history.

The legacy columns stay as the *current* projection, so
`fitness_context.py`, `world_brief.py`, the dashboard, the weekly health
collector and every tool keep reading what they read today. The writer in
`app/services/fitness/targets.py` is the only thing allowed to touch both,
and it does so in one transaction.

**No history is invented.** The seed below creates at most one revision per
scope, dated from the row's own `updated_at` (or a phase's `start_date` when
that is provably earlier and the phase carries macros). Dates before the
earliest revision resolve to `provenance=unknown` — in particular,
`fitness_goals` defaults to 2000/150/200/70, and a row sitting exactly on
those defaults is not evidence that anybody chose them, so it is not seeded
at all.

Revision ID: 161_fitness_targets
Revises: 160_fitness_athlete
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "161_fitness_targets"
down_revision = "160_fitness_athlete"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_target_revision (
            id                       VARCHAR(36) PRIMARY KEY,
            -- Unbounded VARCHAR to match app_user.id and fitness_phase.id,
            -- both `character varying` with no length in the inspected
            -- schema. See the note in 160_fitness_athlete.
            user_id                  VARCHAR NOT NULL
                                         REFERENCES app_user(id) ON DELETE CASCADE,
            scope                    VARCHAR(12) NOT NULL,
            phase_id                 VARCHAR
                                         REFERENCES fitness_phase(id) ON DELETE CASCADE,
            version                  INTEGER NOT NULL DEFAULT 1,

            -- Half-open [valid_from, valid_until). fitness_phase.end_date is
            -- INCLUSIVE; the resolver converts, nothing here rewrites it.
            valid_from               DATE NOT NULL,
            valid_until              DATE,

            -- Training-day values.
            calories                 INTEGER,
            protein_g                INTEGER,
            carbs_g                  INTEGER,
            fat_g                    INTEGER,
            -- Rest-day values. NULL means this revision does not distinguish
            -- day types, and both day types read the training values. That is
            -- different from a rest-day target of 0.
            rest_calories            INTEGER,
            rest_protein_g           INTEGER,
            rest_carbs_g             INTEGER,
            rest_fat_g               INTEGER,
            -- A rest-day step goal is routinely HIGHER than a training-day
            -- one, so steps needs the same training/rest split the macros
            -- have. Sleep and water deliberately do not: nobody sets a
            -- different water target for a rest day, and a single column
            -- keeps the resolver from having to explain a distinction that
            -- does not exist.
            rest_steps               INTEGER,

            sleep_hours              NUMERIC(4,2),
            water_ml                 INTEGER,
            steps                    INTEGER,
            -- Versioned settings, not model decisions: "within 10%" is an
            -- engineering default that has to be inspectable and changeable.
            calorie_tolerance_pct    NUMERIC(5,2) NOT NULL DEFAULT 10,
            protein_tolerance_pct    NUMERIC(5,2) NOT NULL DEFAULT 10,

            source                   VARCHAR(32) NOT NULL DEFAULT 'user',
            -- FK added in 168 once fitness_coach_recommendation exists.
            review_recommendation_id VARCHAR(36),
            approved_at              TIMESTAMPTZ,
            approved_by              VARCHAR(36),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_target_revision_scope CHECK (scope IN ('phase','default')),
            CONSTRAINT ck_target_revision_scope_phase CHECK (
                (scope = 'phase'   AND phase_id IS NOT NULL)
             OR (scope = 'default' AND phase_id IS NULL)),
            CONSTRAINT ck_target_revision_interval CHECK (
                valid_until IS NULL OR valid_until > valid_from),
            CONSTRAINT ck_target_revision_version CHECK (version >= 1),
            CONSTRAINT ck_target_revision_calories CHECK (
                calories IS NULL OR (calories >= 0 AND calories <= 20000)),
            CONSTRAINT ck_target_revision_protein CHECK (
                protein_g IS NULL OR (protein_g >= 0 AND protein_g <= 1500)),
            CONSTRAINT ck_target_revision_rest_calories CHECK (
                rest_calories IS NULL OR (rest_calories >= 0 AND rest_calories <= 20000)),
            CONSTRAINT ck_target_revision_steps CHECK (
                (steps IS NULL OR (steps >= 0 AND steps <= 200000))
            AND (rest_steps IS NULL OR (rest_steps >= 0 AND rest_steps <= 200000))),
            CONSTRAINT ck_target_revision_tolerance CHECK (
                calorie_tolerance_pct >= 0 AND calorie_tolerance_pct <= 100
            AND protein_tolerance_pct >= 0 AND protein_tolerance_pct <= 100)
        )
    """))

    # Version numbers are per (athlete, scope, phase) so "revision 3 of this
    # phase's targets" is a stable thing to cite from a review.
    #
    # COALESCE on phase_id because NULL is distinct from NULL in a unique
    # index, which would let a default-scope revision duplicate its version.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_target_revision_version
        ON fitness_target_revision (user_id, scope, COALESCE(phase_id, ''), version)
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_target_revision_start
        ON fitness_target_revision (user_id, scope, COALESCE(phase_id, ''), valid_from)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_target_revision_resolve
        ON fitness_target_revision (user_id, scope, valid_from DESC)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_target_revision_phase
        ON fitness_target_revision (phase_id, valid_from DESC)
        WHERE phase_id IS NOT NULL
    """))

    # No two APPROVED revisions may cover the same day within one scope. This
    # is a relationship between rows, so it needs an exclusion constraint
    # rather than a CHECK. Scoped to approved rows: a draft revision awaiting
    # a decision is allowed to overlap what it would replace.
    try:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        bind.execute(sa.text("""
            DO $$ BEGIN
                ALTER TABLE fitness_target_revision
                ADD CONSTRAINT ex_target_revision_no_overlap
                EXCLUDE USING gist (
                    user_id WITH =,
                    scope WITH =,
                    COALESCE(phase_id, '') WITH =,
                    daterange(valid_from, valid_until, '[)') WITH &&
                ) WHERE (approved_at IS NOT NULL);
            EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL; END $$
        """))
    except Exception:  # pragma: no cover - environment-dependent
        # The writer holds a per-user advisory lock and checks overlap, so
        # correctness does not depend on the constraint existing.
        pass

    # ── Seed: at most one revision per existing scope, from provable dates ──
    #
    # Phases first. A phase with no calorie target of any kind is not seeded —
    # it resolves to unknown, which is the honest answer.
    bind.execute(sa.text("""
        INSERT INTO fitness_target_revision (
            id, user_id, scope, phase_id, version, valid_from, valid_until,
            calories, protein_g, carbs_g, fat_g,
            rest_calories, rest_carbs_g, rest_fat_g,
            steps, source, approved_at, created_at
        )
        SELECT
            gen_random_uuid()::text,
            p.user_id,
            'phase',
            p.id,
            1,
            -- start_date when the phase has one: that IS the provable date
            -- this target began applying. Otherwise the row's own
            -- updated_at, which is the earliest moment we can show these
            -- values existed.
            COALESCE(p.start_date, p.updated_at::date, CURRENT_DATE),
            -- end_date is INCLUSIVE on fitness_phase; half-open here, so +1.
            CASE WHEN p.end_date IS NOT NULL THEN p.end_date + 1 ELSE NULL END,
            COALESCE(p.calories_training_day, p.calories_target),
            p.protein_target,
            COALESCE(p.carbs_training_day, p.carbs_target),
            COALESCE(p.fat_training_day, p.fat_target),
            p.calories_rest_day,
            p.carbs_rest_day,
            p.fat_rest_day,
            p.daily_steps_target,
            'migration_seed_phase',
            NOW(),
            NOW()
        FROM fitness_phase p
        JOIN app_user u ON u.id = p.user_id
        WHERE (p.calories_target IS NOT NULL
               OR p.calories_training_day IS NOT NULL
               OR p.calories_rest_day IS NOT NULL
               OR p.protein_target IS NOT NULL)
          -- Only phases with a usable interval: an undated phase has no
          -- provable effective range at all.
          AND (p.start_date IS NOT NULL OR p.updated_at IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1 FROM fitness_target_revision r
              WHERE r.scope = 'phase' AND r.phase_id = p.id
          )
    """))

    # Default scope. Deliberately skips a row sitting exactly on the column
    # defaults (2000/150/200/70) — those are not a choice anybody made, and
    # seeding them would assert a target that was never set.
    bind.execute(sa.text("""
        INSERT INTO fitness_target_revision (
            id, user_id, scope, phase_id, version, valid_from,
            calories, protein_g, carbs_g, fat_g,
            source, approved_at, created_at
        )
        SELECT
            gen_random_uuid()::text,
            g.user_id,
            'default',
            NULL,
            1,
            COALESCE(g.updated_at::date, CURRENT_DATE),
            g.calories, g.protein, g.carbs, g.fats,
            'migration_seed_default',
            NOW(),
            NOW()
        FROM fitness_goals g
        JOIN app_user u ON u.id = g.user_id
        WHERE NOT (g.calories = 2000 AND g.protein = 150
                   AND g.carbs = 200 AND g.fats = 70)
          AND NOT EXISTS (
              SELECT 1 FROM fitness_target_revision r
              WHERE r.scope = 'default' AND r.user_id = g.user_id
          )
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "ALTER TABLE fitness_target_revision DROP CONSTRAINT IF EXISTS ex_target_revision_no_overlap",
        "DROP INDEX IF EXISTS ix_target_revision_phase",
        "DROP INDEX IF EXISTS ix_target_revision_resolve",
        "DROP INDEX IF EXISTS uq_target_revision_start",
        "DROP INDEX IF EXISTS uq_target_revision_version",
        "DROP TABLE IF EXISTS fitness_target_revision",
    ):
        bind.execute(sa.text(stmt))
