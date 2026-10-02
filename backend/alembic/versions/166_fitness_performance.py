"""M7 — stable exercise occurrences and precise set metadata.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 13 / §16 M7.

Two problems, both of which silently produce wrong numbers.

**1. `workout_log.weight` is an INTEGER.**

It cannot hold 227.5 lb or 47.5 kg. Every fractional load logged through any
client has been rounded, and the rounding looks exactly like a plateau to a
trend calculation: three sessions at 227.5 lb read as 227, 227, 227. So this
adds `load_value NUMERIC(8,3)` with an explicit `load_unit`, and the integer
column becomes a **compatibility projection** maintained beside it.
`data_access.effective_load` reads the fractional pair first for precisely
this reason, and the old column keeps working for every shipped client.

Nothing truncates: a client that can only send an integer sends an integer,
and a client that sends a fraction gets it stored.

**2. The same exercise twice in one session is indistinguishable.**

Sets are tagged with `active_session_id` plus a text `exercise_id`. An
athlete who benches, does something else, then benches again has one group
of bench sets, so "sets per exercise occurrence" and "how did the second
block compare to the first" are unanswerable.
`fitness_exercise_performance` gives each appearance a stable occurrence
number within the session, and `workout_log.exercise_performance_id` links
sets to it.

Also added:

* `rir` and `rpe_decimal` — `workout_log.rpe` is an INTEGER, so RPE 8.5 does
  not exist today. RIR is a different scale from RPE and gets its own column
  rather than being converted, because the conversion depends on rep range
  and would bake an assumption into stored data.
* `set_role` — `top`, `backoff`, `amrap`, `myo`, `cluster`. **Separate from
  `set_kind`**, which stays exactly `working`/`warmup`/`drop` because
  revision 125's counting rules and `workout_recalc` depend on those three
  values. A top set is a *working* set with a role; adding `top` to
  `set_kind` would make it stop counting toward the target.
* `is_failure`, `actual_rest_seconds`, `tempo`.

Revision ID: 166_fitness_performance
Revises: 165_fitness_exercise_alias
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "166_fitness_performance"
down_revision = "165_fitness_exercise_alias"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_exercise_performance (
            id                  VARCHAR(36) PRIMARY KEY,
            user_id             VARCHAR NOT NULL
                                    REFERENCES app_user(id) ON DELETE CASCADE,
            active_session_id   VARCHAR(36) NOT NULL
                                    REFERENCES active_workout_session(id) ON DELETE CASCADE,
            -- 1, 2, 3… within this session. The athlete who benches, does
            -- something else, then benches again has two occurrences, and
            -- "how did the second block compare" becomes answerable.
            occurrence          INTEGER NOT NULL,
            -- Which snapshot slot this came from, where it came from one.
            template_slot_id    VARCHAR(64),
            exercise_library_id VARCHAR REFERENCES exercise_library(id) ON DELETE SET NULL,
            -- What the snapshot actually said at the time, kept verbatim. A
            -- later template edit must not rewrite what was performed.
            captured_name       VARCHAR(200) NOT NULL,
            captured_variant    VARCHAR(200),
            captured_load_convention VARCHAR(16),
            order_index         INTEGER NOT NULL DEFAULT 0,
            notes               TEXT,
            -- Denormalized from fitness_pain_report for a cheap read; the
            -- reports are the authority.
            pain_reported       BOOLEAN NOT NULL DEFAULT FALSE,
            max_pain_severity   INTEGER,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_exercise_performance_occurrence CHECK (occurrence >= 1),
            CONSTRAINT ck_exercise_performance_pain CHECK (
                max_pain_severity IS NULL OR
                (max_pain_severity >= 0 AND max_pain_severity <= 10)),
            CONSTRAINT ck_exercise_performance_convention CHECK (
                captured_load_convention IS NULL OR captured_load_convention IN
                ('total','per_hand','assisted','bodyweight','stack'))
        )
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_exercise_performance_occurrence
        ON fitness_exercise_performance (active_session_id, occurrence)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_performance_user_session
        ON fitness_exercise_performance (user_id, active_session_id)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_performance_canonical
        ON fitness_exercise_performance (user_id, exercise_library_id)
        WHERE exercise_library_id IS NOT NULL
    """))

    bind.execute(sa.text("""
        ALTER TABLE workout_log
            ADD COLUMN IF NOT EXISTS exercise_performance_id VARCHAR(36)
                REFERENCES fitness_exercise_performance(id) ON DELETE SET NULL,
            -- The actual load. `weight` (INTEGER) is a compatibility
            -- projection of this, kept so every shipped client works; it has
            -- already lost any fraction, which is why effective_load reads
            -- this pair first.
            ADD COLUMN IF NOT EXISTS load_value NUMERIC(8,3),
            ADD COLUMN IF NOT EXISTS load_unit  VARCHAR(8),
            -- Reps in reserve. A different scale from RPE, stored
            -- separately rather than converted: the conversion depends on
            -- rep range, and converting would bake that assumption into the
            -- stored data.
            ADD COLUMN IF NOT EXISTS rir NUMERIC(4,2),
            -- `rpe` is an INTEGER, so RPE 8.5 does not exist today.
            ADD COLUMN IF NOT EXISTS rpe_decimal NUMERIC(4,2),
            -- Roles of a WORKING set, deliberately not values of `set_kind`:
            -- revision 125's counting rules and workout_recalc depend on
            -- set_kind being exactly working/warmup/drop, and a top set that
            -- stopped counting toward the target would be a real bug.
            ADD COLUMN IF NOT EXISTS set_role VARCHAR(16),
            ADD COLUMN IF NOT EXISTS is_failure BOOLEAN,
            ADD COLUMN IF NOT EXISTS actual_rest_seconds INTEGER,
            ADD COLUMN IF NOT EXISTS tempo VARCHAR(16)
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_set_role
                CHECK (set_role IS NULL OR set_role IN
                       ('top','backoff','amrap','myo','cluster','straight'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_load_unit
                CHECK (load_unit IS NULL OR load_unit IN ('kg','lb'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    # A load without a unit is unusable and a unit without a load is
    # meaningless. Either both or neither.
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_load_pair
                CHECK ((load_value IS NULL AND load_unit IS NULL)
                    OR (load_value IS NOT NULL AND load_unit IS NOT NULL));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_effort
                CHECK ((rir IS NULL OR (rir >= 0 AND rir <= 10))
                   AND (rpe_decimal IS NULL OR (rpe_decimal >= 1 AND rpe_decimal <= 10)));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE workout_log ADD CONSTRAINT ck_workout_log_rest
                CHECK (actual_rest_seconds IS NULL
                   OR (actual_rest_seconds >= 0 AND actual_rest_seconds <= 86400));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_workout_log_performance
        ON workout_log (exercise_performance_id)
        WHERE exercise_performance_id IS NOT NULL
    """))

    # Backfill the fractional pair from the existing integer column, in
    # pounds — the legacy contract every client already uses and what
    # `exercise_pr.weight` compares against.
    #
    # This loses nothing (the integer had no fraction to begin with) and
    # makes `effective_load` take the same path for old and new rows. A zero
    # is excluded: `weight = 0` on a bodyweight set means "no external
    # load", not "zero pounds", and storing it as a load would put it in a
    # tonnage sum.
    bind.execute(sa.text("""
        UPDATE workout_log
        SET load_value = weight, load_unit = 'lb'
        WHERE load_value IS NULL AND weight IS NOT NULL AND weight > 0
    """))

    # `set_role` for the one role already recorded elsewhere: revision 125's
    # `set_technique` on template_exercise marks an AMRAP. A set_kind of
    # 'working' with no role stays NULL rather than being guessed as
    # 'straight' — "nobody said" and "a straight set" are different.


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_workout_log_performance",
        "ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_rest",
        "ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_effort",
        "ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_load_pair",
        "ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_load_unit",
        "ALTER TABLE workout_log DROP CONSTRAINT IF EXISTS ck_workout_log_set_role",
        """ALTER TABLE workout_log
               DROP COLUMN IF EXISTS tempo,
               DROP COLUMN IF EXISTS actual_rest_seconds,
               DROP COLUMN IF EXISTS is_failure,
               DROP COLUMN IF EXISTS set_role,
               DROP COLUMN IF EXISTS rpe_decimal,
               DROP COLUMN IF EXISTS rir,
               DROP COLUMN IF EXISTS load_unit,
               DROP COLUMN IF EXISTS load_value,
               DROP COLUMN IF EXISTS exercise_performance_id""",
        "DROP INDEX IF EXISTS ix_exercise_performance_canonical",
        "DROP INDEX IF EXISTS ix_exercise_performance_user_session",
        "DROP INDEX IF EXISTS uq_exercise_performance_occurrence",
        "DROP TABLE IF EXISTS fitness_exercise_performance",
    ):
        bind.execute(sa.text(stmt))
