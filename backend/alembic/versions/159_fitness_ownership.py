"""M0 — ownership prerequisites for the Fitness Coach.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 4 / §16 M0. Everything here is
additive and conflict-free on populated data. It deliberately does NOT add
the foreign keys that would be *correct* on a clean database, because
`routes/fitness.py` spent its life handing out
`os.getenv("SOLO_USER_ID", "default-user")` and some historical rows may be
owned by a string that is not an `app_user.id`. A `REFERENCES app_user(id)`
on those tables would fail the upgrade, and the only ways to make it succeed
are to delete history or to reassign it to a guessed owner. Both lose
information that `backend/scripts/fitness_backfill_audit.py` exists to
preserve as a reviewable report.

So: indexes and a quarantine record now; constraints only after a reviewed
reconciliation, as a later revision. Child APIs and
`app/services/fitness/data_access.py` enforce ownership in the meantime,
which is where it has to be enforced anyway — a UUID FK proves a parent
exists, never that it belongs to the requester.

What this adds:

1. `(user_id, <event date>)` indexes on the tables every analytics window
   scans. Without them a 28-day review is a sequential scan of someone's
   whole history, and the plan's bounded-query rule is unenforceable in
   practice.
2. `fitness_ownership_quarantine` — a durable record of rows whose owner
   could not be resolved, so the decision is not re-derived (and possibly
   re-derived differently) on every audit run.
3. `exercise_library.owner_user_id` / `visibility`, nullable and defaulted
   to the current behaviour. The table has no owner column at all today;
   adding one without changing any existing row's meaning is the
   prerequisite for Step 12's scoped catalog. Nothing is classified here.

Revision ID: 159_fitness_ownership
Revises: 158_reminder_delivery_state
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "159_fitness_ownership"
down_revision = "158_reminder_delivery_state"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ── 1. Owner+date indexes for bounded analytics windows ──────────────
    #
    # The column each one leads with is the one the analytics actually filter
    # on, which is not always the obvious one:
    #   * food_log by `logged_at` — when it was eaten, not `created_at`.
    #   * workout_log by `session_date`, with a COALESCE fallback index for
    #     the older rows where it was never populated.
    #   * health_metric by `recorded_at` — the observation time.
    for stmt in (
        """CREATE INDEX IF NOT EXISTS ix_health_metric_user_type_time
           ON health_metric (user_id, metric_type, recorded_at DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_daily_recovery_log_user_date
           ON daily_recovery_log (user_id, log_date DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_workout_log_user_session_date
           ON workout_log (user_id, session_date DESC)
           WHERE session_date IS NOT NULL""",
        """CREATE INDEX IF NOT EXISTS ix_workout_log_user_logged_fallback
           ON workout_log (user_id, COALESCE(session_time, created_at) DESC)
           WHERE session_date IS NULL""",
        """CREATE INDEX IF NOT EXISTS ix_workout_log_user_canonical_exercise
           ON workout_log (user_id, exercise_library_id, session_date DESC)
           WHERE exercise_library_id IS NOT NULL AND voided_at IS NULL""",
        """CREATE INDEX IF NOT EXISTS ix_workout_session_user_date
           ON workout_session (user_id, session_date DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_active_workout_session_user_started
           ON active_workout_session (user_id, started_at DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_weight_trend_user_date
           ON weight_trend (user_id, date DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_exercise_pr_user_name
           ON exercise_pr (user_id, exercise_name, achieved_at DESC)""",
        """CREATE INDEX IF NOT EXISTS ix_fitness_phase_user_dates
           ON fitness_phase (user_id, start_date, end_date)""",
        """CREATE INDEX IF NOT EXISTS ix_fitness_template_user_phase
           ON fitness_template (user_id, phase_id)""",
        """CREATE INDEX IF NOT EXISTS ix_progress_photo_user_taken
           ON progress_photo (user_id, taken_at DESC)""",
    ):
        bind.execute(sa.text(stmt))

    # A partial unique index, not a constraint: exactly one active program
    # per athlete going forward. Partial so it only covers `is_active = true`
    # — an athlete keeps any number of inactive historical programs.
    #
    # Created as a *report*, not enforced, if duplicates already exist: the
    # audit script reports them (`duplicate_active_program`) and a reviewed
    # reconciliation deactivates the shadowed one. Attempting to create the
    # index on conflicting data would fail the whole upgrade, so this is
    # guarded.
    duplicates = bind.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT user_id FROM fitness_program
            WHERE is_active = true
            GROUP BY user_id HAVING COUNT(*) > 1
        ) dupes
    """)).scalar()
    if not duplicates:
        bind.execute(sa.text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_fitness_program_one_active
            ON fitness_program (user_id) WHERE is_active = true
        """))

    # ── 2. Durable quarantine record ─────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_ownership_quarantine (
            id              VARCHAR(36) PRIMARY KEY,
            table_name      VARCHAR(63)  NOT NULL,
            row_id          VARCHAR(64)  NOT NULL,
            -- The literal value found in user_id. NOT an FK: the whole point
            -- is that it does not resolve to an app_user.
            observed_owner  VARCHAR(128),
            reason          VARCHAR(64)  NOT NULL,
            -- 'unresolved' until a human decides; then 'assigned' or
            -- 'abandoned'. Never set by an automated pass.
            status          VARCHAR(20)  NOT NULL DEFAULT 'unresolved',
            resolved_owner  VARCHAR(36)  REFERENCES app_user(id) ON DELETE SET NULL,
            reviewed_by     VARCHAR(36),
            reviewed_at     TIMESTAMPTZ,
            notes           TEXT,
            first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_fitness_quarantine_status CHECK (
                status IN ('unresolved', 'assigned', 'abandoned')
            )
        )
    """))
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fitness_quarantine_row
        ON fitness_ownership_quarantine (table_name, row_id)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_fitness_quarantine_unresolved
        ON fitness_ownership_quarantine (table_name)
        WHERE status = 'unresolved'
    """))

    # ── 3. exercise_library scope, nullable and behaviour-preserving ──────
    #
    # `visibility` defaults to 'unscoped' — not 'global'. Every existing row
    # keeps working exactly as it does now (readers that do not mention
    # visibility see everything), but no row is *asserted* to be public.
    # `exercise_library_seed.py` derived rows from names already in people's
    # logs, so declaring them all global would publish user-created exercise
    # names. Step 12 classifies them from a reviewed usage report.
    bind.execute(sa.text("""
        ALTER TABLE exercise_library
            ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)
                REFERENCES app_user(id) ON DELETE CASCADE,
            ADD COLUMN IF NOT EXISTS visibility VARCHAR(20)
                NOT NULL DEFAULT 'unscoped',
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS scope_reviewed_at TIMESTAMPTZ
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE exercise_library ADD CONSTRAINT ck_exercise_library_visibility
                CHECK (visibility IN ('unscoped', 'global', 'private', 'shared'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    # A private row must name its owner; a global row must not have one.
    # Checked as a constraint because this is the invariant Step 12's
    # classification pass has to satisfy, and a classification bug that
    # produced an ownerless private row would silently hide the exercise.
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE exercise_library ADD CONSTRAINT ck_exercise_library_scope_owner
                CHECK (
                    (visibility = 'private' AND owner_user_id IS NOT NULL)
                    OR (visibility = 'global' AND owner_user_id IS NULL)
                    OR visibility IN ('unscoped', 'shared')
                );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_library_owner
        ON exercise_library (owner_user_id)
        WHERE owner_user_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_exercise_library_visibility
        ON exercise_library (visibility) WHERE archived_at IS NULL
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_exercise_library_visibility",
        "DROP INDEX IF EXISTS ix_exercise_library_owner",
        "ALTER TABLE exercise_library DROP CONSTRAINT IF EXISTS ck_exercise_library_scope_owner",
        "ALTER TABLE exercise_library DROP CONSTRAINT IF EXISTS ck_exercise_library_visibility",
        """ALTER TABLE exercise_library
               DROP COLUMN IF EXISTS scope_reviewed_at,
               DROP COLUMN IF EXISTS archived_at,
               DROP COLUMN IF EXISTS visibility,
               DROP COLUMN IF EXISTS owner_user_id""",
        "DROP INDEX IF EXISTS ix_fitness_quarantine_unresolved",
        "DROP INDEX IF EXISTS uq_fitness_quarantine_row",
        "DROP TABLE IF EXISTS fitness_ownership_quarantine",
        "DROP INDEX IF EXISTS uq_fitness_program_one_active",
        "DROP INDEX IF EXISTS ix_progress_photo_user_taken",
        "DROP INDEX IF EXISTS ix_fitness_template_user_phase",
        "DROP INDEX IF EXISTS ix_fitness_phase_user_dates",
        "DROP INDEX IF EXISTS ix_exercise_pr_user_name",
        "DROP INDEX IF EXISTS ix_weight_trend_user_date",
        "DROP INDEX IF EXISTS ix_active_workout_session_user_started",
        "DROP INDEX IF EXISTS ix_workout_session_user_date",
        "DROP INDEX IF EXISTS ix_workout_log_user_canonical_exercise",
        "DROP INDEX IF EXISTS ix_workout_log_user_logged_fallback",
        "DROP INDEX IF EXISTS ix_workout_log_user_session_date",
        "DROP INDEX IF EXISTS ix_daily_recovery_log_user_date",
        "DROP INDEX IF EXISTS ix_health_metric_user_type_time",
    ):
        bind.execute(sa.text(stmt))
