"""M11 — progress-photo capture metadata and a truthful cleanup record.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 26 / §5.5 / §16 M11.

EXTENDS `progress_photo`; does not replace it. The iOS app reads every
existing column and its endpoint shape, so a parallel table would mean two
photo stores and a migration the phone cannot be made to perform.

What is added and why:

* **`view`** — front/side/back/other. Without it a comparison pairs a front
  shot with a side shot, which is not a change in the athlete.
* **`period_id`** — links a set of shots taken in one sitting, the way
  `fitness_measurement_period` links a tape session. Three photos from one
  morning are one capture, not three unrelated points.
* **`capture_protocol` / `lighting` / `distance_cm`** — the conditions.
  Photo-to-photo difference is dominated by lighting and distance, so a pair
  taken differently is not comparable and has to be able to say so.
* **`bodyweight_observation_id`** — a REFERENCE to the canonical weight
  observation, replacing the free-floating `bodyweight` float as the thing a
  reader should trust. The old column stays as display context: §26.1 says
  the legacy snapshot is never an automatic authoritative ingestion, so it
  is neither deleted nor promoted.
* **`consent_analysis`** — explicit, default FALSE. Running a vision model
  over somebody's body requires more than them having uploaded the photo,
  and Step 27's analysis is gated on this column.
* **`cleanup_state` / `cleanup_attempts` / `cleanup_error`** — the truthful
  part. Deleting the row while the blob delete failed leaves private bytes
  in object storage with nothing recording that they exist. The row is now
  marked `pending_cleanup` instead, so a sweep can retry and an audit can
  see what is outstanding.

Revision ID: 170_fitness_photo_meta
Revises: 169_fitness_cadence
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "170_fitness_photo_meta"
down_revision = "169_fitness_cadence"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    for column, ddl in (
        # front/side/back/other. A comparison across views is not a change
        # in the athlete.
        ("view", "VARCHAR(16)"),
        ("period_id", "VARCHAR(36)"),
        ("capture_protocol", "VARCHAR(200)"),
        ("lighting", "VARCHAR(60)"),
        ("distance_cm", "INTEGER"),
        # A reference, not a copy. `health_metric` is the authority for a
        # body number; a float on this row cannot be corrected or dated.
        ("bodyweight_observation_id", "VARCHAR(36)"),
        # Explicit and default FALSE. Uploading a photo is not consent to
        # run a vision model over it.
        ("consent_analysis", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("consent_analysis_at", "TIMESTAMPTZ"),
        ("analysis_status", "VARCHAR(20)"),
        # Truthful cleanup. See the module docstring.
        ("cleanup_state", "VARCHAR(20)"),
        ("cleanup_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("cleanup_error", "VARCHAR(300)"),
        ("deleted_at", "TIMESTAMPTZ"),
        # The exact bytes stored, so a re-upload of the same image is
        # detectable and a pair analysis can be keyed on content.
        ("content_sha256", "VARCHAR(64)"),
        ("updated_at", "TIMESTAMPTZ"),
    ):
        bind.execute(sa.text(
            f"ALTER TABLE progress_photo ADD COLUMN IF NOT EXISTS {column} {ddl}"
        ))

    # Reuse `fitness_measurement_period` rather than inventing a photo
    # period table: a tape session and a photo set are the same event most
    # of the time, and two period tables would make "that morning" have two
    # ids. The FK is SET NULL so deleting a period never destroys a photo.
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_progress_photo_period'
            ) THEN
                ALTER TABLE progress_photo
                ADD CONSTRAINT fk_progress_photo_period
                FOREIGN KEY (period_id)
                REFERENCES fitness_measurement_period(id) ON DELETE SET NULL;
            END IF;
        END $$
    """))
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_progress_photo_view'
            ) THEN
                ALTER TABLE progress_photo
                ADD CONSTRAINT ck_progress_photo_view
                CHECK (view IS NULL OR view IN
                       ('front', 'side', 'back', 'other'));
            END IF;
        END $$
    """))
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_progress_photo_cleanup'
            ) THEN
                ALTER TABLE progress_photo
                ADD CONSTRAINT ck_progress_photo_cleanup
                CHECK (cleanup_state IS NULL OR cleanup_state IN
                       ('pending_cleanup', 'cleaned', 'orphaned'));
            END IF;
        END $$
    """))
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_progress_photo_consent_time'
            ) THEN
                ALTER TABLE progress_photo
                ADD CONSTRAINT ck_progress_photo_consent_time
                CHECK (NOT consent_analysis OR consent_analysis_at IS NOT NULL);
            END IF;
        END $$
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_progress_photo_user_taken
        ON progress_photo (user_id, taken_at DESC NULLS LAST)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_progress_photo_period
        ON progress_photo (period_id) WHERE period_id IS NOT NULL
    """))
    # The sweep's index: rows whose bytes still need deleting.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_progress_photo_pending_cleanup
        ON progress_photo (cleanup_state, cleanup_attempts)
        WHERE cleanup_state = 'pending_cleanup'
    """))
    # And the one that keeps a soft-deleted row out of every list.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_progress_photo_live
        ON progress_photo (user_id, created_at DESC)
        WHERE deleted_at IS NULL
    """))

    # A photo's period must belong to the same athlete. §5: an FK to a UUID
    # alone does not enforce ownership, and a photo attached to another
    # athlete's capture session would put it in their comparison.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION progress_photo_same_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            period_owner VARCHAR;
        BEGIN
            IF NEW.period_id IS NOT NULL THEN
                SELECT user_id INTO period_owner
                FROM fitness_measurement_period WHERE id = NEW.period_id;
                IF period_owner IS NOT NULL AND period_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'photo owner % does not match capture-period owner %',
                        NEW.user_id, period_owner
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_progress_photo_same_owner ON progress_photo
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_progress_photo_same_owner
        BEFORE INSERT OR UPDATE ON progress_photo
        FOR EACH ROW EXECUTE FUNCTION progress_photo_same_owner()
    """))

    # The retry sweep for orphaned private bytes. Hourly: these are a
    # privacy debt, and an overnight-only sweep leaves somebody's photo in
    # object storage for a working day after they deleted it.
    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, timezone,
            args, kwargs, queue, enabled, editable, source, visibility,
            created_at, updated_at
        ) VALUES (
            'fitness_photo_cleanup_retry',
            'Retry progress-photo blob cleanup',
            'Retries object-storage deletes for photos whose rows are marked '
            'pending_cleanup. These are private bytes the athlete asked to '
            'have deleted, so the retry is hourly rather than nightly.',
            'fitness',
            'app.tasks.fitness_coach.retry_photo_cleanup',
            'cron', '20 * * * *', 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'maintenance',
            TRUE, TRUE, 'system', 'system',
            NOW(), NOW()
        )
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DELETE FROM scheduled_job WHERE key = 'fitness_photo_cleanup_retry'",
        "DROP TRIGGER IF EXISTS trg_progress_photo_same_owner ON progress_photo",
        "DROP FUNCTION IF EXISTS progress_photo_same_owner()",
        "DROP INDEX IF EXISTS ix_progress_photo_live",
        "DROP INDEX IF EXISTS ix_progress_photo_pending_cleanup",
        "DROP INDEX IF EXISTS ix_progress_photo_period",
        "DROP INDEX IF EXISTS ix_progress_photo_user_taken",
        "ALTER TABLE progress_photo DROP CONSTRAINT IF EXISTS ck_progress_photo_consent_time",
        "ALTER TABLE progress_photo DROP CONSTRAINT IF EXISTS ck_progress_photo_cleanup",
        "ALTER TABLE progress_photo DROP CONSTRAINT IF EXISTS ck_progress_photo_view",
        "ALTER TABLE progress_photo DROP CONSTRAINT IF EXISTS fk_progress_photo_period",
    ):
        bind.execute(sa.text(stmt))
    for column in (
        "updated_at", "content_sha256", "deleted_at", "cleanup_error",
        "cleanup_attempts", "cleanup_state", "analysis_status",
        "consent_analysis_at", "consent_analysis",
        "bodyweight_observation_id", "distance_cm", "lighting",
        "capture_protocol", "period_id", "view",
    ):
        bind.execute(sa.text(
            f"ALTER TABLE progress_photo DROP COLUMN IF EXISTS {column}"
        ))
