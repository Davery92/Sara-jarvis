"""M4 — subjective check-in fields on `daily_recovery_log`.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 9 / §16 M4. Extends the existing daily
row rather than creating a second daily-truth table, because two tables each
holding "how did you sleep" is how two screens come to show different
answers for the same day.

Everything defaults to NULL or `unknown`. Nothing here backfills a subjective
value: nobody recorded their stress level last March, and a default of 5
would be a fabricated data point that reads exactly like a real one.

Notable decisions:

* **`nutrition_status` defaults to `'unknown'`, not `'partial'`.** A day
  with no meals logged is not a day with partial intake — it is a day nobody
  told us about. The difference matters because "complete days" is the
  denominator for every nutrition average, and a wrongly-partial day makes
  an average of nothing look like an average of something.
* **`subjective_readiness` is separate from the computed readiness score.**
  `recovery_score.compute_readiness()` returns 100 for an empty input; the
  athlete saying "I feel like a 4" is a different fact from a formula with
  no inputs. Neither substitutes for the other.
* **`field_sources` records which field came from where.** A PATCH that
  omits `hrv` must not erase a value HealthKit wrote, and a correction has
  to be distinguishable from an original reading.
* **A scale CHECK on every 1-10 field.** `soreness_level` already had one;
  the new fields get the same treatment, because a 0 or an 11 arriving from
  a client would silently skew every mean computed from it. Directions are
  documented in `app/schemas/fitness_coach.py:SCALE_DIRECTIONS` — without
  that, "soreness improved" and "soreness increased" are the same number
  moving.

Revision ID: 163_fitness_checkin
Revises: 162_fitness_observations
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "163_fitness_checkin"
down_revision = "162_fitness_observations"
branch_labels = None
depends_on = None

# 1-10, lower-is-better or higher-is-better per SCALE_DIRECTIONS.
_SCALE_FIELDS = (
    "sleep_quality",
    "energy",
    "fatigue",
    "stress",
    "motivation",
    "subjective_readiness",
)


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        ALTER TABLE daily_recovery_log
            ADD COLUMN IF NOT EXISTS bedtime_at             TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS wake_at                TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS sleep_quality          INTEGER,
            ADD COLUMN IF NOT EXISTS energy                 INTEGER,
            ADD COLUMN IF NOT EXISTS fatigue                INTEGER,
            ADD COLUMN IF NOT EXISTS stress                 INTEGER,
            ADD COLUMN IF NOT EXISTS motivation             INTEGER,
            -- The athlete's own answer, never the computed score.
            ADD COLUMN IF NOT EXISTS subjective_readiness   INTEGER,
            ADD COLUMN IF NOT EXISTS nutrition_status       VARCHAR(12)
                NOT NULL DEFAULT 'unknown',
            ADD COLUMN IF NOT EXISTS nutrition_completed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS row_version            INTEGER
                NOT NULL DEFAULT 1,
            -- {field: 'manual'|'apple_health'|'correction'|...}. Without it a
            -- PATCH cannot tell a value it should leave alone from one it
            -- owns.
            ADD COLUMN IF NOT EXISTS field_sources          JSONB
                NOT NULL DEFAULT '{}'::jsonb
    """))

    for field in _SCALE_FIELDS:
        bind.execute(sa.text(f"""
            DO $$ BEGIN
                ALTER TABLE daily_recovery_log
                ADD CONSTRAINT ck_daily_recovery_{field}
                    CHECK ({field} IS NULL OR ({field} >= 1 AND {field} <= 10));
            EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE daily_recovery_log
            ADD CONSTRAINT ck_daily_recovery_nutrition_status
                CHECK (nutrition_status IN ('unknown','partial','complete'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    # A completion timestamp without a completion is incoherent, and so is a
    # completion with no timestamp — "when did you confirm this day" has to
    # be answerable, because editing a meal afterwards invalidates it.
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE daily_recovery_log
            ADD CONSTRAINT ck_daily_recovery_nutrition_completed
                CHECK (
                    (nutrition_status = 'complete' AND nutrition_completed_at IS NOT NULL)
                 OR (nutrition_status <> 'complete')
                );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE daily_recovery_log
            ADD CONSTRAINT ck_daily_recovery_sleep_episode
                CHECK (
                    bedtime_at IS NULL OR wake_at IS NULL
                 OR (wake_at > bedtime_at
                     AND wake_at - bedtime_at <= INTERVAL '24 hours')
                );
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE daily_recovery_log
            ADD CONSTRAINT ck_daily_recovery_row_version CHECK (row_version >= 1);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    # The nutrition-completeness read: "how many complete days in this
    # window", which is the denominator for every nutrition average.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_daily_recovery_nutrition_complete
        ON daily_recovery_log (user_id, log_date DESC)
        WHERE nutrition_status = 'complete'
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_daily_recovery_nutrition_complete"))
    for name in (
        "ck_daily_recovery_row_version",
        "ck_daily_recovery_sleep_episode",
        "ck_daily_recovery_nutrition_completed",
        "ck_daily_recovery_nutrition_status",
        *[f"ck_daily_recovery_{f}" for f in _SCALE_FIELDS],
    ):
        bind.execute(sa.text(
            f"ALTER TABLE daily_recovery_log DROP CONSTRAINT IF EXISTS {name}"
        ))
    bind.execute(sa.text("""
        ALTER TABLE daily_recovery_log
            DROP COLUMN IF EXISTS field_sources,
            DROP COLUMN IF EXISTS row_version,
            DROP COLUMN IF EXISTS nutrition_completed_at,
            DROP COLUMN IF EXISTS nutrition_status,
            DROP COLUMN IF EXISTS subjective_readiness,
            DROP COLUMN IF EXISTS motivation,
            DROP COLUMN IF EXISTS stress,
            DROP COLUMN IF EXISTS fatigue,
            DROP COLUMN IF EXISTS energy,
            DROP COLUMN IF EXISTS sleep_quality,
            DROP COLUMN IF EXISTS wake_at,
            DROP COLUMN IF EXISTS bedtime_at
    """))
