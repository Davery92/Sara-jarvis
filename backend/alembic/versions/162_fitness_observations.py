"""M3 — units, provenance and correction metadata on `health_metric`.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 8 / §16 M3. Purely additive columns on
the table that is already the single authority for observed body numbers.

The thing this does **not** do is touch `ix_health_metric_dedup`, the UNIQUE
index on `(user_id, metric_type, recorded_at)`. Two live writers depend on it
by name in their `ON CONFLICT` clauses — `routes/health_metrics.py`'s iOS
batch ingest and `services/health_metric_mirror.py`'s HRV mirror. Widening or
replacing it would make both fail at runtime, in a code path whose whole job
is to not lose a sync. Step 8's rule is explicit: "Preserve existing
`(user,type,time)` uniqueness initially... Only widen uniqueness after
updating HealthKit ON CONFLICT callers together."

So where two genuinely different sources collide at an identical timestamp,
the loser is **recorded as a conflict** rather than silently discarded or
silently preferred. `source_conflict` holds what was rejected and why, which
is the information a "two scales disagree" question needs and which
`DO NOTHING` currently throws away.

Columns:

* `unit` — the canonical unit this value is in. Nullable, because every
  existing row predates it: `data_access.LEGACY_METRIC_UNITS` resolves those
  from the *traced writers*, and anything untraced stays `UNKNOWN`. No
  backfill guesses a unit from a value's magnitude; 180 lb and 180 kg are
  both real bodyweights.
* `original_value` / `original_unit` — what the source actually sent, when a
  conversion happened. Without this a kg→lb conversion is irreversible and a
  later unit-policy change cannot be re-derived.
* `external_id` — the provider's own sample id, for idempotent retries. A
  partial-unique index on `(user_id, source, external_id)` makes a replayed
  HealthKit batch a no-op without depending on timestamps matching to the
  microsecond.
* `logical_date` — the athlete-local calendar day this observation belongs
  to. Stored, not derived at read time, because the athlete's timezone can
  change and a past observation's day must not move when it does.
* `supersedes_id` / `superseded_by_id` / `correction_reason` — a manual
  correction points at what it replaces, and the replaced row stays. Analytics
  filter on `superseded_by_id IS NULL`.
* `source_quality` — `measured` | `derived` | `synthesized_stamp` | `manual`.
  `synthesized_stamp` is the honest label for the HRV mirror's 06:00 ET
  stamp: that is not when the reading was taken, and a metric that claims to
  be a 6am measurement when it is a daily aggregate would mislead any
  bedtime/wake analysis built on it.

Revision ID: 162_fitness_observations
Revises: 161_fitness_targets
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "162_fitness_observations"
down_revision = "161_fitness_targets"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        ALTER TABLE health_metric
            ADD COLUMN IF NOT EXISTS unit              VARCHAR(16),
            ADD COLUMN IF NOT EXISTS original_value    NUMERIC(14,4),
            ADD COLUMN IF NOT EXISTS original_unit     VARCHAR(16),
            ADD COLUMN IF NOT EXISTS external_id       VARCHAR(200),
            ADD COLUMN IF NOT EXISTS logical_date      DATE,
            ADD COLUMN IF NOT EXISTS source_quality    VARCHAR(24),
            ADD COLUMN IF NOT EXISTS supersedes_id     VARCHAR(36),
            ADD COLUMN IF NOT EXISTS superseded_by_id  VARCHAR(36),
            ADD COLUMN IF NOT EXISTS correction_reason VARCHAR(200),
            ADD COLUMN IF NOT EXISTS source_conflict   JSONB
    """))

    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE health_metric ADD CONSTRAINT ck_health_metric_source_quality
                CHECK (source_quality IS NULL OR source_quality IN
                       ('measured','derived','synthesized_stamp','manual'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    # A row cannot supersede itself, which a careless correction would do.
    bind.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE health_metric ADD CONSTRAINT ck_health_metric_not_self_superseding
                CHECK (supersedes_id IS NULL OR supersedes_id <> id);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """))

    # Provider idempotency. Partial, because `external_id` is NULL for every
    # manual entry and for every row written before this revision — a full
    # unique index would be fine in Postgres (NULLs are distinct) but a
    # partial one states the intent and stays small.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_health_metric_external_sample
        ON health_metric (user_id, source, external_id)
        WHERE external_id IS NOT NULL
    """))

    # The read path for analytics: one athlete, one metric type, one local
    # day, excluding corrected rows.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_health_metric_logical_day
        ON health_metric (user_id, metric_type, logical_date DESC)
        WHERE superseded_by_id IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_health_metric_superseded
        ON health_metric (superseded_by_id)
        WHERE superseded_by_id IS NOT NULL
    """))

    # Backfill `logical_date` from `recorded_at` in the athlete's own
    # timezone, defaulting to ET — which is what every existing writer
    # assumed anyway, since Sara has had one user.
    #
    # `recorded_at` is timestamptz, so `AT TIME ZONE` yields that zone's
    # wall-clock and `::date` its calendar day. Done in one statement because
    # it is a pure projection of data already present: no value is invented,
    # and re-running it is idempotent.
    bind.execute(sa.text("""
        UPDATE health_metric hm
        SET logical_date = (
            hm.recorded_at AT TIME ZONE COALESCE(
                (SELECT p.timezone FROM fitness_athlete_profile p
                 WHERE p.user_id = hm.user_id),
                'America/New_York'
            )
        )::date
        WHERE hm.logical_date IS NULL
    """))

    # `unit` is deliberately NOT backfilled here. The traced legacy units live
    # in `app/services/fitness/data_access.py:LEGACY_METRIC_UNITS` and are
    # applied on read, so a type whose writer was never traced resolves to
    # UNKNOWN and is reported as an unresolved unit rather than being assigned
    # a plausible-looking one. Writing a guess into the column would make the
    # guess indistinguishable from a recorded fact forever.
    #
    # New writes set it explicitly; `observations.py` refuses a write with no
    # unit for a type it does not recognise.

    # `source_quality` for the one case already known to be synthesized: the
    # HRV mirror stamps a daily reading at 06:00 ET, which is not when it was
    # measured. Labelling it is what stops a future bedtime/wake analysis
    # treating that stamp as an observation time.
    bind.execute(sa.text("""
        UPDATE health_metric
        SET source_quality = 'synthesized_stamp'
        WHERE source_quality IS NULL
          AND metric_type = 'hrv_morning'
          AND metadata ? 'morning_reading'
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_health_metric_superseded",
        "DROP INDEX IF EXISTS ix_health_metric_logical_day",
        "DROP INDEX IF EXISTS uq_health_metric_external_sample",
        "ALTER TABLE health_metric DROP CONSTRAINT IF EXISTS ck_health_metric_not_self_superseding",
        "ALTER TABLE health_metric DROP CONSTRAINT IF EXISTS ck_health_metric_source_quality",
        """ALTER TABLE health_metric
               DROP COLUMN IF EXISTS source_conflict,
               DROP COLUMN IF EXISTS correction_reason,
               DROP COLUMN IF EXISTS superseded_by_id,
               DROP COLUMN IF EXISTS supersedes_id,
               DROP COLUMN IF EXISTS source_quality,
               DROP COLUMN IF EXISTS logical_date,
               DROP COLUMN IF EXISTS external_id,
               DROP COLUMN IF EXISTS original_unit,
               DROP COLUMN IF EXISTS original_value,
               DROP COLUMN IF EXISTS unit""",
    ):
        bind.execute(sa.text(stmt))
