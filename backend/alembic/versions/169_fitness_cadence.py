"""M10 — per-athlete coaching cadence, and a durable occurrence ledger.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 24 / §5.5 / §16 M10.

Two tables, and the second one is the whole point.

**`fitness_coaching_schedule`** is per-athlete and **disabled by default**,
with a separate consent toggle per kind. "Turn on coaching" as one switch
would make "remind me to weigh in" and "write me a weekly review" the same
decision, and they are not — one is a nudge, the other is a minute of GPU
time and an opinion about the athlete's diet.

For the 14- and 28-day cadences it stores an **anchor date** rather than a
cron expression. A cron of `*/14` on the day-of-month field does not mean
every fourteen days: it means the 1st, 15th and 29th, so January gives a
14-day gap then a 14-day gap then a 3-day gap. An anchor plus a day count is
the only arithmetic that means what it says.

**`fitness_coaching_job_run`** is the occurrence ledger, with a unique key on
`(user_id, kind, occurrence_at)`. This is what makes "retry/restart never
produces two reviews per occurrence" true rather than hoped for:

* `DBScheduler` seeds UTC `last_run_at`, which makes a daily ET cron fire
  twice (see `tests/test_db_scheduler_beat_double_fire.py`). The sweep WILL
  be double-dispatched, and the ledger absorbs it into one artifact. A
  double-fired sweep in a test is that known behaviour, not a ledger bug.
* `DBScheduler` also marks `last_status='success'` at DISPATCH time, so a
  green `scheduled_job` row proves only that the sweep was sent. The
  ledger's own `status` is the only record of whether the work happened.
* A claim that enqueues and then fails leaves a `claimed` row with a
  `claimed_at`, which the next sweep reclaims after a timeout rather than
  losing the occurrence silently.

The sweep itself is ONE global `scheduled_job` row. An athlete never supplies
a task name, a queue, or kwargs: the only thing their settings control is
whether their own preference row is enabled and when. A per-athlete
`scheduled_job` would put `task_name` behind a user-facing API, which is
arbitrary code execution with extra steps.

Revision ID: 169_fitness_cadence
Revises: 168_fitness_review_audit
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "169_fitness_cadence"
down_revision = "168_fitness_review_audit"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ── fitness_coaching_schedule ──────────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_coaching_schedule (
            id                  VARCHAR(36) PRIMARY KEY,
            user_id             VARCHAR NOT NULL
                                    REFERENCES app_user(id) ON DELETE CASCADE,
            kind                VARCHAR(32) NOT NULL,

            -- BOTH default false, and they are different questions.
            -- `enabled` is "is this cadence switched on"; `consented` is
            -- "did the athlete agree to be contacted about it". A cadence
            -- that runs and stores a review without delivering anything is
            -- a legitimate state; delivering without consent is not.
            enabled             BOOLEAN NOT NULL DEFAULT FALSE,
            consented           BOOLEAN NOT NULL DEFAULT FALSE,
            consented_at        TIMESTAMPTZ,

            -- Athlete-local wall clock, with the zone stored beside it. A
            -- UTC time would drift an hour twice a year relative to the
            -- morning it was chosen for.
            local_time          TIME NOT NULL DEFAULT '07:00',
            timezone            VARCHAR(64) NOT NULL DEFAULT 'America/New_York',

            -- For weekly cadences: ISO weekdays (1=Monday).
            weekdays            JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- For 14/28-day cadences: an anchor plus a count, because a
            -- cron's `*/14` day-of-month is NOT every fourteen days.
            cadence_days        INTEGER,
            anchor_date         DATE,

            next_due_at         TIMESTAMPTZ,
            last_evaluated_at   TIMESTAMPTZ,
            last_completed_at   TIMESTAMPTZ,
            snoozed_until       TIMESTAMPTZ,

            -- Bumped on every edit. A queued job re-reads the preference
            -- before acting and compares this: an occurrence claimed before
            -- the athlete turned the cadence off must not run.
            version             INTEGER NOT NULL DEFAULT 1,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_coaching_schedule_kind
                CHECK (kind IN (
                    'daily_checkin', 'weekly_review', 'biweekly_review',
                    'monthly_review', 'tape_measurement', 'progress_photo'
                )),
            -- A cadence in days needs an anchor to count from, and an
            -- anchor with no count is meaningless.
            CONSTRAINT ck_coaching_schedule_cadence_pair
                CHECK ((cadence_days IS NULL AND anchor_date IS NULL)
                       OR (cadence_days IS NOT NULL AND anchor_date IS NOT NULL)),
            CONSTRAINT ck_coaching_schedule_cadence_days
                CHECK (cadence_days IS NULL OR cadence_days BETWEEN 1 AND 365),
            -- Consent carries a time. "Consented at some point" is not a
            -- record of consent.
            CONSTRAINT ck_coaching_schedule_consent_time
                CHECK (NOT consented OR consented_at IS NOT NULL),
            CONSTRAINT ck_coaching_schedule_version CHECK (version >= 1)
        )
    """))

    # One preference row per athlete per kind. Two rows for one kind would
    # make "is this on?" have two answers.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_coaching_schedule_user_kind
        ON fitness_coaching_schedule (user_id, kind)
    """))
    # The sweep's own index: only enabled, consented, due rows.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coaching_schedule_due
        ON fitness_coaching_schedule (next_due_at)
        WHERE enabled AND consented
    """))

    # ── fitness_coaching_job_run ───────────────────────────────────────────
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS fitness_coaching_job_run (
            id                  VARCHAR(36) PRIMARY KEY,
            user_id             VARCHAR NOT NULL
                                    REFERENCES app_user(id) ON DELETE CASCADE,
            schedule_id         VARCHAR(36)
                REFERENCES fitness_coaching_schedule(id) ON DELETE SET NULL,
            kind                VARCHAR(32) NOT NULL,

            -- The occurrence this run IS. Truncated to the due minute by the
            -- claimer, so two sweeps in the same minute compute the same
            -- value and collide on the unique index.
            occurrence_at       TIMESTAMPTZ NOT NULL,

            status              VARCHAR(20) NOT NULL DEFAULT 'claimed',
            -- The preference version at claim time. A job compares it before
            -- acting: an occurrence claimed before the athlete turned the
            -- cadence off must become a noop, not run.
            schedule_version    INTEGER,

            claimed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            enqueued_at         TIMESTAMPTZ,
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,

            attempts            INTEGER NOT NULL DEFAULT 0,
            celery_task_id      VARCHAR(64),

            -- What the run produced, when it produced something.
            review_id           VARCHAR(36)
                REFERENCES fitness_coach_review(id) ON DELETE SET NULL,
            candidate_id        VARCHAR(64),

            -- A category and a short line. Never a prompt, for the same
            -- reason `fitness_coach_review` does not store one.
            error_category      VARCHAR(40),
            error_detail        VARCHAR(500),
            -- Why nothing was delivered, when that is the outcome. A
            -- suppression is a RECORDED result, not a silent bypass.
            noop_reason         VARCHAR(60),

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_coaching_run_status
                CHECK (status IN (
                    'claimed', 'enqueued', 'running', 'completed',
                    'failed', 'noop'
                )),
            CONSTRAINT ck_coaching_run_failed_has_reason
                CHECK (status <> 'failed' OR error_category IS NOT NULL),
            -- A noop says why. "Nothing happened" with no reason is
            -- indistinguishable from a bug.
            CONSTRAINT ck_coaching_run_noop_has_reason
                CHECK (status <> 'noop' OR noop_reason IS NOT NULL),
            CONSTRAINT ck_coaching_run_attempts CHECK (attempts >= 0)
        )
    """))

    # THE constraint. One artifact per occurrence, whatever the scheduler
    # does — and `DBScheduler` is known to double-fire a daily ET cron.
    bind.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_coaching_run_occurrence
        ON fitness_coaching_job_run (user_id, kind, occurrence_at)
    """))
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coaching_run_user_recent
        ON fitness_coaching_job_run (user_id, kind, occurrence_at DESC)
    """))
    # The reclaim index: rows stuck before a terminal state.
    bind.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS ix_coaching_run_unfinished
        ON fitness_coaching_job_run (claimed_at)
        WHERE status IN ('claimed', 'enqueued', 'running')
    """))

    # Ownership is enforced, not assumed (§5): a run hanging off another
    # athlete's schedule would act on one athlete's cadence under another's
    # id.
    bind.execute(sa.text("""
        CREATE OR REPLACE FUNCTION fitness_coaching_run_same_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            schedule_owner VARCHAR;
            review_owner VARCHAR;
        BEGIN
            IF NEW.schedule_id IS NOT NULL THEN
                SELECT user_id INTO schedule_owner
                FROM fitness_coaching_schedule WHERE id = NEW.schedule_id;
                IF schedule_owner IS NOT NULL
                   AND schedule_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'coaching run owner % does not match schedule owner %',
                        NEW.user_id, schedule_owner
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF NEW.review_id IS NOT NULL THEN
                SELECT user_id INTO review_owner
                FROM fitness_coach_review WHERE id = NEW.review_id;
                IF review_owner IS NOT NULL AND review_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'coaching run owner % does not match review owner %',
                        NEW.user_id, review_owner
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    bind.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_fitness_coaching_run_same_owner
        ON fitness_coaching_job_run
    """))
    bind.execute(sa.text("""
        CREATE TRIGGER trg_fitness_coaching_run_same_owner
        BEFORE INSERT OR UPDATE ON fitness_coaching_job_run
        FOR EACH ROW EXECUTE FUNCTION fitness_coaching_run_same_owner()
    """))

    # ── The one global sweep ───────────────────────────────────────────────
    #
    # ONE row, `source='system'`, `editable=false`. The athlete's settings
    # control their own preference row and nothing else: a per-athlete
    # `scheduled_job` would put `task_name` behind a user-facing API, which
    # is arbitrary code execution with extra steps.
    #
    # Every five minutes rather than on a daily cron, because the sweep's
    # job is to notice that somebody's local 07:00 has arrived — and local
    # 07:00 is a different UTC instant for every athlete and twice a year
    # for the same one.
    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, interval_seconds, timezone,
            args, kwargs, queue, enabled, editable, source, visibility,
            created_at, updated_at
        ) VALUES (
            'fitness_coaching_due_sweep',
            'Fitness coaching due sweep',
            'Claims due per-athlete coaching occurrences and enqueues them. '
            'One global row: an athlete''s settings control only their own '
            'cadence preference, never a task name or a queue.',
            'fitness',
            'app.tasks.fitness_coach.sweep_due_occurrences',
            'interval', 300, 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'health',
            TRUE, FALSE, 'system', 'system',
            NOW(), NOW()
        )
        ON CONFLICT (key) DO NOTHING
    """))

    # And the expiry sweep for stale recommendations, which Step 19 wrote the
    # task for and nothing was calling.
    bind.execute(sa.text("""
        INSERT INTO scheduled_job (
            key, display_name, description, category, task_name,
            schedule_kind, cron_expr, timezone,
            args, kwargs, queue, enabled, editable, source, visibility,
            created_at, updated_at
        ) VALUES (
            'fitness_recommendation_expiry',
            'Expire stale coach recommendations',
            'Marks passed-deadline coaching proposals expired. They are '
            'retained, never deleted — "what did you suggest and what did I '
            'do about it" has to stay answerable.',
            'fitness',
            'app.tasks.fitness_coach.expire_recommendations',
            'cron', '15 4 * * *', 'America/New_York',
            '[]'::jsonb, '{}'::jsonb, 'maintenance',
            TRUE, TRUE, 'system', 'system',
            NOW(), NOW()
        )
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    for stmt in (
        "DELETE FROM scheduled_job WHERE key = 'fitness_recommendation_expiry'",
        "DELETE FROM scheduled_job WHERE key = 'fitness_coaching_due_sweep'",
        "DROP TRIGGER IF EXISTS trg_fitness_coaching_run_same_owner ON fitness_coaching_job_run",
        "DROP FUNCTION IF EXISTS fitness_coaching_run_same_owner()",
        "DROP INDEX IF EXISTS ix_coaching_run_unfinished",
        "DROP INDEX IF EXISTS ix_coaching_run_user_recent",
        "DROP INDEX IF EXISTS uq_coaching_run_occurrence",
        "DROP TABLE IF EXISTS fitness_coaching_job_run",
        "DROP INDEX IF EXISTS ix_coaching_schedule_due",
        "DROP INDEX IF EXISTS uq_coaching_schedule_user_kind",
        "DROP TABLE IF EXISTS fitness_coaching_schedule",
    ):
        bind.execute(sa.text(stmt))
