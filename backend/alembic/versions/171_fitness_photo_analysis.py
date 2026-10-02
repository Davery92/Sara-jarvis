"""M12 — structured, immutable photo observations.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 27 / §5.5 / §16 M12.

What the schema makes impossible, which is the point:

* **No body-fat, weight or lean-mass column.** §5.5: "no body-fat
  percentage field or diagnosis". `PhotoObservationV1` has no field for one
  either, and its validator rejects a number smuggled into prose — a model
  with nowhere to put a composition estimate puts it in the summary, where
  it reads as an observation that `health_metric` never sees.
* **No image bytes, no raw model text, no reasoning chain.** The photo
  lives in object storage behind an owner check; a copy here would be a
  second place to leak it from, and a stored chain-of-thought is private
  musing about somebody's body kept for no reader.
* **A pair cannot cross owners.** A trigger checks the analysis, the source
  photo and the comparison photo all belong to one athlete. §5: an FK to a
  UUID alone does not enforce ownership, and a pair spanning two people
  would describe one person's body inside the other's record.
* **Immutable once terminal.** A `BEFORE UPDATE` trigger freezes the
  output, the versions and the model, the same way `fitness_coach_review`
  is frozen. An observation whose output can be rewritten is a cache.

The idempotency key is `(user_id, kind, source_photo_id, compare_photo_id,
prompt_version, capture_hash)`: the same pair, the same prompt and the same
bytes is one analysis. `capture_hash` in the key is what makes a re-upload
of a changed image a NEW analysis rather than a silent reuse of a
description of different pixels.

Revision ID: 171_fitness_photo_analysis
Revises: 170_fitness_photo_meta
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "171_fitness_photo_analysis"
down_revision = "170_fitness_photo_meta"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_photo_analysis (
            id                      VARCHAR(36) PRIMARY KEY,
            user_id                 VARCHAR NOT NULL
                                        REFERENCES app_user(id) ON DELETE CASCADE,

            kind                    VARCHAR(8) NOT NULL DEFAULT 'single',
            source_photo_id         VARCHAR NOT NULL
                REFERENCES progress_photo(id) ON DELETE CASCADE,
            compare_photo_id        VARCHAR
                REFERENCES progress_photo(id) ON DELETE CASCADE,

            view                    VARCHAR(16),
            source_captured_at      TIMESTAMPTZ,
            compare_captured_at     TIMESTAMPTZ,

            -- The fingerprint of the exact bytes analysed. A replaced or
            -- deleted source invalidates the result rather than leaving a
            -- description of an image nobody can see.
            capture_hash            VARCHAR(64),

            status                  VARCHAR(20) NOT NULL DEFAULT 'pending',

            -- The model that ACTUALLY answered and where. For vision this
            -- also catches the case a text-only probe cannot: a llama.cpp
            -- server started without `--mmproj` serves the same model over
            -- the same API and silently ignores the image.
            model_requested         VARCHAR(120),
            model_actual            VARCHAR(120),
            provider                VARCHAR(60),
            endpoint                VARCHAR(200),
            vision_verified         BOOLEAN NOT NULL DEFAULT FALSE,

            prompt_version          VARCHAR(40) NOT NULL,
            prompt_hash             VARCHAR(64),
            output_schema_version   INTEGER,

            -- VALIDATED structured output only. No raw text, no reasoning
            -- chain, no image bytes.
            output                  JSONB,
            summary                 TEXT,

            failure_category        VARCHAR(40),
            failure_detail          VARCHAR(500),

            attempts                INTEGER NOT NULL DEFAULT 0,
            evaluated_at            TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_photo_analysis_status
                CHECK (status IN ('pending', 'running', 'complete', 'failed',
                                  'inconclusive', 'source_gone')),
            CONSTRAINT ck_photo_analysis_kind
                CHECK (kind IN ('single', 'pair')),
            -- A pair needs a second photo; a single must not have one.
            CONSTRAINT ck_photo_analysis_pair_shape
                CHECK ((kind = 'pair' AND compare_photo_id IS NOT NULL)
                       OR (kind = 'single' AND compare_photo_id IS NULL)),
            -- A photo cannot be compared with itself: the answer would be
            -- "identical" and it would look like a finding.
            CONSTRAINT ck_photo_analysis_distinct_pair
                CHECK (compare_photo_id IS NULL
                       OR compare_photo_id <> source_photo_id),
            CONSTRAINT ck_photo_analysis_complete_has_output
                CHECK (status <> 'complete' OR output IS NOT NULL),
            CONSTRAINT ck_photo_analysis_failed_has_reason
                CHECK (status <> 'failed' OR failure_category IS NOT NULL),
            CONSTRAINT ck_photo_analysis_attempts CHECK (attempts >= 0)
        )
    """))

    # Idempotency. The same pair, the same prompt and the same BYTES is one
    # analysis — `capture_hash` in the key makes a changed image a new
    # analysis rather than a silent reuse of a description of other pixels.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_photo_analysis_idempotency
        ON fitness_photo_analysis (
            user_id, kind, source_photo_id,
            COALESCE(compare_photo_id, ''), prompt_version,
            COALESCE(capture_hash, '')
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_photo_analysis_user_recent
        ON fitness_photo_analysis (user_id, created_at DESC)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_photo_analysis_source
        ON fitness_photo_analysis (source_photo_id)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_photo_analysis_unfinished
        ON fitness_photo_analysis (created_at)
        WHERE status IN ('pending', 'running')
    """))

    # Ownership across all three rows. A pair spanning two athletes would
    # describe one person's body inside the other's record.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_photo_analysis_same_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            source_owner VARCHAR;
            compare_owner VARCHAR;
        BEGIN
            SELECT user_id INTO source_owner
            FROM progress_photo WHERE id = NEW.source_photo_id;
            IF source_owner IS NULL THEN
                RAISE EXCEPTION 'source photo % does not exist',
                    NEW.source_photo_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF source_owner <> NEW.user_id THEN
                RAISE EXCEPTION
                    'analysis owner % does not match source photo owner %',
                    NEW.user_id, source_owner
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.compare_photo_id IS NOT NULL THEN
                SELECT user_id INTO compare_owner
                FROM progress_photo WHERE id = NEW.compare_photo_id;
                IF compare_owner IS NULL THEN
                    RAISE EXCEPTION 'comparison photo % does not exist',
                        NEW.compare_photo_id
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                IF compare_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'a comparison cannot span two athletes (% and %)',
                        NEW.user_id, compare_owner
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_photo_analysis_same_owner
        ON fitness_photo_analysis
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_photo_analysis_same_owner
        BEFORE INSERT OR UPDATE ON fitness_photo_analysis
        FOR EACH ROW EXECUTE FUNCTION fitness_photo_analysis_same_owner()
    """))

    # Immutability once terminal, the same discipline as
    # `fitness_coach_review`. An observation whose output can be rewritten
    # is a cache, not an observation.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_photo_analysis_freeze()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status IN ('complete', 'failed', 'inconclusive',
                              'source_gone') THEN
                IF NEW.output          IS DISTINCT FROM OLD.output
                OR NEW.summary         IS DISTINCT FROM OLD.summary
                OR NEW.model_actual    IS DISTINCT FROM OLD.model_actual
                OR NEW.prompt_version  IS DISTINCT FROM OLD.prompt_version
                OR NEW.prompt_hash     IS DISTINCT FROM OLD.prompt_hash
                OR NEW.capture_hash    IS DISTINCT FROM OLD.capture_hash
                OR NEW.source_photo_id IS DISTINCT FROM OLD.source_photo_id
                OR NEW.compare_photo_id IS DISTINCT FROM OLD.compare_photo_id
                OR NEW.user_id         IS DISTINCT FROM OLD.user_id
                THEN
                    RAISE EXCEPTION
                        'fitness_photo_analysis % is terminal (%); its inputs '
                        'and output are immutable. Record a new analysis.',
                        OLD.id, OLD.status
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_photo_analysis_freeze
        ON fitness_photo_analysis
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_photo_analysis_freeze
        BEFORE UPDATE ON fitness_photo_analysis
        FOR EACH ROW EXECUTE FUNCTION fitness_photo_analysis_freeze()
    """))

    # Belt and braces against the one column that must never be added. A
    # future migration adding `body_fat_percent` here would be caught at
    # deploy time rather than when a number reaches an athlete.
    bind.execute(sa.text("""
        DO $$
        DECLARE
            forbidden TEXT;
        BEGIN
            SELECT column_name INTO forbidden
            FROM information_schema.columns
            WHERE table_name = 'fitness_photo_analysis'
              AND (column_name LIKE '%body_fat%'
                   OR column_name LIKE '%lean_mass%'
                   OR column_name = 'bmi'
                   OR column_name LIKE '%estimated_weight%')
            LIMIT 1;
            IF forbidden IS NOT NULL THEN
                RAISE EXCEPTION
                    'fitness_photo_analysis must not hold a body-composition '
                    'column (found %) — a photograph cannot support one',
                    forbidden;
            END IF;
        END $$
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP TRIGGER IF EXISTS trg_photo_analysis_freeze ON fitness_photo_analysis",
        "DROP FUNCTION IF EXISTS fitness_photo_analysis_freeze()",
        "DROP TRIGGER IF EXISTS trg_photo_analysis_same_owner ON fitness_photo_analysis",
        "DROP FUNCTION IF EXISTS fitness_photo_analysis_same_owner()",
        "DROP INDEX IF EXISTS ix_photo_analysis_unfinished",
        "DROP INDEX IF EXISTS ix_photo_analysis_source",
        "DROP INDEX IF EXISTS ix_photo_analysis_user_recent",
        "DROP INDEX IF EXISTS uq_photo_analysis_idempotency",
        "DROP TABLE IF EXISTS fitness_photo_analysis",
    ):
        bind.execute(sa.text(stmt))
