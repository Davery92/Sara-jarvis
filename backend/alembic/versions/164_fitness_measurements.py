"""M5 — extensible measurement definitions and measurement periods.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 10 / §16 M5.

The design goal is that **adding a new thing to measure never needs a
migration**. A column per circumference is how a schema ends up with
`waist_cm`, `chest_cm`, `left_arm_cm`, `right_arm_cm`, … and then cannot hold
"forearm at the widest point, measured standing" without another deploy. So:

* `fitness_measurement_type` is the *descriptor* — a stable code, a label, a
  quantity, a canonical unit, whether sides apply, and the protocol text that
  makes two readings comparable. Global seeds have `owner_user_id IS NULL`;
  an athlete's own custom code is private to them.
* `fitness_measurement_period` groups one tape session or photo set, so
  "waist 81.5, chest 104, arm 38.5" is one sitting rather than three
  unrelated points.
* **The measured numbers stay in `health_metric`.** There is no
  `fitness_body_measurement` table. Body observations have one authority
  (§4.2), and a second numeric store would immediately be able to disagree
  with it — most obviously about bodyweight, which is both a tape-session
  reading and a `weight` observation.

The descriptor/period references live in `health_metric.metadata`, with a
generated column and index so a query by type code is not a JSONB scan of
every observation the athlete has.

Why a generated column rather than a plain one: `metadata` is written by
several existing paths, and a plain column would need every one of them to
remember to populate it. A generated column cannot drift from the JSONB it
is derived from.

Revision ID: 164_fitness_measurements
Revises: 163_fitness_checkin
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "164_fitness_measurements"
down_revision = "163_fitness_checkin"
branch_labels = None
depends_on = None

# Common circumferences, seeded globally. Deliberately small: §15 forbids a
# massive catalog in a foundation phase, and an athlete can add their own
# without a migration — which is the property being built here.
#
# `sides` is True only where left/right is a real distinction. A waist has no
# sides, and offering them would invite two incomparable waist series.
_SEEDS = [
    ("waist_circumference", "Waist", True, False,
     "At the navel, relaxed, at the end of a normal exhale. Tape snug, not compressing."),
    ("chest_circumference", "Chest", True, False,
     "At the widest point across the nipples, arms relaxed at the sides."),
    ("hip_circumference", "Hips", True, False,
     "At the widest point of the glutes, feet together."),
    ("neck_circumference", "Neck", True, False,
     "Below the larynx, tape level, shoulders relaxed."),
    ("upper_arm_circumference", "Upper arm", True, True,
     "At the widest point, arm relaxed and hanging. Keep flexed/unflexed consistent."),
    ("forearm_circumference", "Forearm", True, True,
     "At the widest point below the elbow, arm relaxed."),
    ("thigh_circumference", "Thigh", True, True,
     "At the widest point below the glute fold, standing, weight even."),
    ("calf_circumference", "Calf", True, True,
     "At the widest point, standing, weight even."),
]


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_measurement_type (
            id                VARCHAR(36) PRIMARY KEY,
            -- Normalized by app.schemas.fitness_coach.normalize_code, the
            -- same normalizer exercise aliases use, so "Waist
            -- Circumference" and "waist_circumference" cannot become two
            -- different keys in two different tables.
            code              VARCHAR(60) NOT NULL,
            label             VARCHAR(120) NOT NULL,
            quantity          VARCHAR(16) NOT NULL,
            canonical_unit    VARCHAR(16) NOT NULL,
            allows_side       BOOLEAN NOT NULL DEFAULT FALSE,
            allowed_sites     JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- What makes two readings of this comparable. A waist measured
            -- at the navel and one at the narrowest point are different
            -- series, and the difference between them is not a change.
            protocol_guidance TEXT,
            -- NULL = a global seed, visible to everyone.
            owner_user_id     VARCHAR REFERENCES app_user(id) ON DELETE CASCADE,
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_measurement_type_quantity CHECK (
                quantity IN ('mass','length','time','count','volume','rate','score'))
        )
    """))

    # Two namespaces, both unique within themselves: one global and one per
    # athlete. COALESCE because NULL is distinct from NULL in a unique index,
    # which would otherwise let two global seeds share a code.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_measurement_type_code_scope
        ON fitness_measurement_type (COALESCE(owner_user_id, ''), code)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_measurement_type_owner
        ON fitness_measurement_type (owner_user_id)
        WHERE owner_user_id IS NOT NULL AND is_active
    """))

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_measurement_period (
            id                 VARCHAR(36) PRIMARY KEY,
            user_id            VARCHAR NOT NULL
                                   REFERENCES app_user(id) ON DELETE CASCADE,
            measured_on        DATE NOT NULL,
            measured_at        TIMESTAMPTZ,
            protocol           VARCHAR(200),
            notes              TEXT,
            -- Links a tape session to a photo set taken the same morning.
            photo_period_label VARCHAR(120),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_measurement_period_user_date
        ON fitness_measurement_period (user_id, measured_on DESC)
    """))

    # The descriptor/period/site/side references for a measurement live in
    # `health_metric.metadata`. Generated columns project the two that are
    # queried, so "every waist reading in this window" is an index scan
    # rather than a JSONB filter over the athlete's entire observation
    # history.
    #
    # Generated rather than plain: `metadata` already has several writers,
    # and a plain column would need every one to remember to populate it. A
    # generated column cannot drift from its source.
    bind.execute(sa.text("""
        ALTER TABLE health_metric
            ADD COLUMN IF NOT EXISTS measurement_type_code VARCHAR(60)
                GENERATED ALWAYS AS (metadata->>'measurement_type_code') STORED,
            ADD COLUMN IF NOT EXISTS measurement_period_id VARCHAR(36)
                GENERATED ALWAYS AS (metadata->>'measurement_period_id') STORED
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_health_metric_measurement
        ON health_metric (user_id, measurement_type_code, logical_date DESC)
        WHERE measurement_type_code IS NOT NULL AND superseded_by_id IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_health_metric_measurement_period
        ON health_metric (measurement_period_id)
        WHERE measurement_period_id IS NOT NULL
    """))

    for code, label, has_protocol, sides, protocol in _SEEDS:
        bind.execute(sa.text("""
            INSERT INTO fitness_measurement_type
                (id, code, label, quantity, canonical_unit, allows_side,
                 protocol_guidance, owner_user_id)
            SELECT gen_random_uuid()::text, CAST(:code AS VARCHAR),
                   CAST(:label AS VARCHAR), 'length', 'cm',
                   CAST(:sides AS BOOLEAN), CAST(:protocol AS TEXT), NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM fitness_measurement_type
                WHERE code = CAST(:code AS VARCHAR) AND owner_user_id IS NULL
            )
        """), {"code": code, "label": label, "sides": sides, "protocol": protocol})


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_health_metric_measurement_period",
        "DROP INDEX IF EXISTS ix_health_metric_measurement",
        """ALTER TABLE health_metric
               DROP COLUMN IF EXISTS measurement_period_id,
               DROP COLUMN IF EXISTS measurement_type_code""",
        "DROP INDEX IF EXISTS ix_measurement_period_user_date",
        "DROP TABLE IF EXISTS fitness_measurement_period",
        "DROP INDEX IF EXISTS ix_measurement_type_owner",
        "DROP INDEX IF EXISTS uq_measurement_type_code_scope",
        "DROP TABLE IF EXISTS fitness_measurement_type",
    ):
        bind.execute(sa.text(stmt))
