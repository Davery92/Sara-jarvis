"""M8 — pain reports.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 13 / §16 M8.

A pain report is **what the athlete said**, and the schema is shaped so it
cannot become anything else:

* There is no diagnosis, condition or injury-type column. "Right forearm
  hurts on barbell curls" is data; naming a condition is a clinical
  conclusion this system does not draw, and a stored diagnosis would be
  cited as fact by every downstream reader forever.
* `pain_present` is an explicit boolean and is **not** defaulted. A session
  with no report is `unknown`, not pain-free — "nobody asked" and "nothing
  hurt" support completely different coaching, and the difference is exactly
  what a missing row means.
* Severity is 0-10 self-reported, and 0 is a real answer meaning "I was
  asked and nothing hurt".

Derived summaries count **distinct sessions with a report**, never set
count. Four reports across four sets of one session is one session with
pain; counting sets would make a single bad session look like a pattern.

Revision ID: 167_fitness_pain
Revises: 166_fitness_performance
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "167_fitness_pain"
down_revision = "166_fitness_performance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_pain_report (
            id                      VARCHAR(36) PRIMARY KEY,
            user_id                 VARCHAR NOT NULL
                                        REFERENCES app_user(id) ON DELETE CASCADE,
            -- All three optional: pain during a known set, during a known
            -- exercise block, during a session generally, or on a day with
            -- no session at all. A report with no session is still a report.
            exercise_performance_id VARCHAR(36)
                REFERENCES fitness_exercise_performance(id) ON DELETE SET NULL,
            active_session_id       VARCHAR(36)
                REFERENCES active_workout_session(id) ON DELETE SET NULL,
            workout_set_id          VARCHAR
                REFERENCES workout_log(id) ON DELETE SET NULL,
            exercise_library_id     VARCHAR
                REFERENCES exercise_library(id) ON DELETE SET NULL,

            occurred_at             TIMESTAMPTZ NOT NULL,
            -- Athlete-local, stored rather than derived: the athlete's
            -- timezone can change and a past report's day must not move.
            logical_date            DATE NOT NULL,

            -- Explicit, never defaulted. A session with no row is UNKNOWN,
            -- not pain-free.
            pain_present            BOOLEAN NOT NULL,
            -- 0-10 self-reported. 0 means "asked, nothing hurt".
            severity                INTEGER,
            location                VARCHAR(120),
            side                    VARCHAR(8),
            onset                   VARCHAR(24),
            context                 VARCHAR(200),
            notes                   TEXT,

            -- A correction supersedes rather than overwrites: "I said 7 but
            -- it was more like 3" is a second statement, and both are things
            -- the athlete said.
            superseded_by_id        VARCHAR(36)
                REFERENCES fitness_pain_report(id) ON DELETE SET NULL,
            resolved_at             TIMESTAMPTZ,
            source                  VARCHAR(32) NOT NULL DEFAULT 'manual',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_pain_severity CHECK (
                severity IS NULL OR (severity >= 0 AND severity <= 10)),
            CONSTRAINT ck_pain_side CHECK (
                side IS NULL OR side IN ('left','right','both','none')),
            CONSTRAINT ck_pain_onset CHECK (
                onset IS NULL OR onset IN
                ('sudden','gradual','pre_existing','unknown')),
            -- Pain present with no severity is allowed (they may not have
            -- rated it). Severity above zero with pain_present false is
            -- incoherent and would make a "no pain" report count as pain.
            CONSTRAINT ck_pain_coherent CHECK (
                pain_present OR severity IS NULL OR severity = 0),
            CONSTRAINT ck_pain_not_self_superseding CHECK (
                superseded_by_id IS NULL OR superseded_by_id <> id)
        )
    """))

    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_pain_report_user_date
        ON fitness_pain_report (user_id, logical_date DESC)
        WHERE superseded_by_id IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_pain_report_canonical_exercise
        ON fitness_pain_report (user_id, exercise_library_id, logical_date DESC)
        WHERE exercise_library_id IS NOT NULL AND superseded_by_id IS NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_pain_report_session
        ON fitness_pain_report (active_session_id)
        WHERE active_session_id IS NOT NULL
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_pain_report_performance
        ON fitness_pain_report (exercise_performance_id)
        WHERE exercise_performance_id IS NOT NULL
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DROP INDEX IF EXISTS ix_pain_report_performance",
        "DROP INDEX IF EXISTS ix_pain_report_session",
        "DROP INDEX IF EXISTS ix_pain_report_canonical_exercise",
        "DROP INDEX IF EXISTS ix_pain_report_user_date",
        "DROP TABLE IF EXISTS fitness_pain_report",
    ):
        bind.execute(sa.text(stmt))
