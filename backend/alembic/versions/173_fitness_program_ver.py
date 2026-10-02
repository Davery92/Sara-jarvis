"""M14 — immutable program/template revisions and reviewable drafts.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 29 / §16 M14.

The problem this solves is that programming data lives in three places
that can disagree: `fitness_template.exercises` (the JSON the live workout
view reads), `template_exercise` (the relational rows the editor writes),
and `exercises[i].set_plan` (a top/backoff table keyed by *program* week).
A change that writes one and not the others produces a program that looks
edited on one screen and unchanged on another — and a past session's
snapshot that no longer matches the template it was performed from.

What the schema makes impossible:

* **Editing an activated revision.** A `BEFORE UPDATE` trigger freezes the
  snapshot, the hash and the version once `activated_at` is set. A review
  cited that program and a logged session was performed from it; a
  revision whose contents can change is not a record of anything.
* **Activating a draft twice, or activating two drafts into one
  revision.** `(program_id, revision)` is unique, and a draft carries the
  revision it produced. Acceptance is idempotent on the draft.
* **Applying a draft to a program that moved.** The draft stores
  `base_revision`; acceptance compares it to the program's current one and
  refuses a mismatch. §29.6: a backdated revision needs an explicit effect
  scope, which is a column rather than an assumption.
* **A model-activated plan.** `activated_by` is NOT NULL on an activated
  revision and a CHECK forbids the string 'model'. §29.2: the LLM produces
  a constrained draft, full stop. The only way to a live template is an
  owner-origin acceptance that leaves a row.
* **A draft that is accepted without having been valid.** `validation` is
  NOT NULL on an accepted draft and a CHECK requires it to record zero
  blocking findings.

Revision ID: 173_fitness_program_ver
Revises: 172_fitness_science
"""
from alembic import op

revision = "173_fitness_program_ver"
down_revision = "172_fitness_science"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_program_revision (
            id               VARCHAR PRIMARY KEY,
            user_id          VARCHAR NOT NULL
                             REFERENCES app_user(id) ON DELETE CASCADE,
            program_id       VARCHAR NOT NULL,
            revision         INTEGER NOT NULL,
            label            VARCHAR(200),
            -- The whole program as prescribed at this revision: phases,
            -- sessions, slots, sets. One blob rather than a shadow copy of
            -- four tables, because what a reader needs is "what was the
            -- plan on that date", answerable without reconstructing joins
            -- against rows that have since changed.
            snapshot         JSONB NOT NULL,
            snapshot_version INTEGER NOT NULL DEFAULT 1,
            content_hash     VARCHAR(64) NOT NULL,
            source           VARCHAR(20) NOT NULL DEFAULT 'manual',
            draft_id         VARCHAR,
            -- Which phase and dates this revision governs. §29.6: a
            -- backdated revision states its scope rather than leaving a
            -- reader to infer it from created_at.
            effective_from   DATE,
            effective_to     DATE,
            effect_scope     VARCHAR(20) NOT NULL DEFAULT 'forward',
            activated_at     TIMESTAMPTZ,
            activated_by     VARCHAR,
            superseded_by_id VARCHAR,
            notes            TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_program_revision UNIQUE (program_id, revision),
            CONSTRAINT ck_program_revision_positive CHECK (revision >= 1),
            CONSTRAINT ck_program_revision_source CHECK (source IN (
                'manual', 'import', 'draft', 'migration'
            )),
            CONSTRAINT ck_program_revision_scope CHECK (effect_scope IN (
                'forward', 'retroactive'
            )),
            -- An activated revision says who activated it, and it was not
            -- a model. §29.2: the only route from a draft to a live
            -- template is an owner-origin acceptance.
            CONSTRAINT ck_program_revision_activated_by CHECK (
                activated_at IS NULL
                OR (activated_by IS NOT NULL
                    AND activated_by NOT IN ('model', 'llm', 'system',
                                             'autonomous'))
            ),
            CONSTRAINT ck_program_revision_dates CHECK (
                effective_from IS NULL OR effective_to IS NULL
                OR effective_to >= effective_from
            ),
            -- A draft-sourced revision names its draft, so the trail runs
            -- both ways.
            CONSTRAINT ck_program_revision_draft CHECK (
                source <> 'draft' OR draft_id IS NOT NULL
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_program_revision_owner
        ON fitness_program_revision (user_id, program_id, revision DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_program_revision_active
        ON fitness_program_revision (user_id, program_id)
        WHERE activated_at IS NOT NULL AND superseded_by_id IS NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_template_revision (
            id                  VARCHAR PRIMARY KEY,
            user_id             VARCHAR NOT NULL,
            template_id         VARCHAR NOT NULL,
            revision            INTEGER NOT NULL,
            program_revision_id VARCHAR
                                REFERENCES fitness_program_revision(id)
                                ON DELETE CASCADE,
            -- The typed `PrescribedSession`, which is the shape both the
            -- JSON column and the relational rows are rendered from. One
            -- source, two projections — the three-way disagreement this
            -- table exists to end.
            snapshot            JSONB NOT NULL,
            snapshot_version    INTEGER NOT NULL DEFAULT 1,
            content_hash        VARCHAR(64) NOT NULL,
            working_sets        INTEGER,
            estimated_minutes   NUMERIC(6, 1),
            activated_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_template_revision UNIQUE (template_id, revision),
            CONSTRAINT ck_template_revision_positive CHECK (revision >= 1)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_template_revision_owner
        ON fitness_template_revision (user_id, template_id, revision DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_program_draft (
            id                 VARCHAR PRIMARY KEY,
            user_id            VARCHAR NOT NULL
                               REFERENCES app_user(id) ON DELETE CASCADE,
            kind               VARCHAR(20) NOT NULL,
            status             VARCHAR(20) NOT NULL DEFAULT 'draft',
            program_id         VARCHAR,
            phase_id           VARCHAR,
            -- The revision the draft was built against. Acceptance
            -- compares this to the program's current revision and refuses
            -- a mismatch: a draft built on revision 4 cannot be applied to
            -- revision 6 without being re-read.
            base_revision      INTEGER,
            payload            JSONB NOT NULL,
            payload_version    INTEGER NOT NULL DEFAULT 1,
            validation         JSONB,
            -- Separate from `validation` so an unanswered question is
            -- visible without parsing the findings list.
            open_questions     JSONB NOT NULL DEFAULT '[]'::jsonb,
            model_actual       VARCHAR(120),
            prompt_version     VARCHAR(40),
            prompt_hash        VARCHAR(64),
            science_citations  JSONB,
            requested_by       VARCHAR(20) NOT NULL DEFAULT 'user',
            decided_at         TIMESTAMPTZ,
            decided_by         VARCHAR,
            decision_reason    TEXT,
            resulting_revision_id VARCHAR
                               REFERENCES fitness_program_revision(id)
                               ON DELETE SET NULL,
            valid_until        TIMESTAMPTZ,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_program_draft_kind CHECK (
                kind IN ('program', 'block', 'week')
            ),
            CONSTRAINT ck_program_draft_status CHECK (status IN (
                'draft', 'accepted', 'rejected', 'stale', 'expired'
            )),
            CONSTRAINT ck_program_draft_requested_by CHECK (
                requested_by IN ('user', 'schedule', 'coach')
            ),
            -- A decision records who made it and why. An accept with no
            -- reason is a click, and the reason is the audit.
            CONSTRAINT ck_program_draft_decided CHECK (
                status IN ('draft', 'stale', 'expired')
                OR (decided_at IS NOT NULL AND decided_by IS NOT NULL)
            ),
            -- An accepted draft was validated and had nothing blocking.
            -- §29 completion: no unreviewed model plan is activated.
            CONSTRAINT ck_program_draft_accept_validated CHECK (
                status <> 'accepted'
                OR (validation IS NOT NULL
                    AND resulting_revision_id IS NOT NULL
                    AND COALESCE(
                        jsonb_array_length(open_questions), 0) = 0)
            ),
            -- And it was not a model that accepted it.
            CONSTRAINT ck_program_draft_decided_by CHECK (
                decided_by IS NULL
                OR decided_by NOT IN ('model', 'llm', 'autonomous')
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_program_draft_owner
        ON fitness_program_draft (user_id, status, created_at DESC)
    """)
    # One live draft per program at a time. A second would mean two
    # proposals for the same weeks, and accepting both in either order
    # produces a different program.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_program_draft_open
        ON fitness_program_draft (user_id, COALESCE(program_id, ''), kind)
        WHERE status = 'draft'
    """)

    # ── Owner coherence ────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_program_owner_matches()
        RETURNS TRIGGER AS $$
        DECLARE
            program_owner VARCHAR;
            template_owner VARCHAR;
        BEGIN
            IF TG_TABLE_NAME = 'fitness_template_revision' THEN
                SELECT user_id INTO template_owner
                FROM fitness_template WHERE id = NEW.template_id;
                -- A template may legitimately not exist yet: a draft can
                -- propose a new session, and its revision is written in the
                -- same transaction as the template. Only a MISMATCH is an
                -- error.
                IF template_owner IS NOT NULL
                   AND template_owner <> NEW.user_id THEN
                    RAISE EXCEPTION
                        'template revision owner % does not match template '
                        'owner %', NEW.user_id, template_owner;
                END IF;
                IF NEW.program_revision_id IS NOT NULL THEN
                    SELECT user_id INTO program_owner
                    FROM fitness_program_revision
                    WHERE id = NEW.program_revision_id;
                    IF program_owner IS DISTINCT FROM NEW.user_id THEN
                        RAISE EXCEPTION
                            'template revision owner % does not match '
                            'program revision owner %',
                            NEW.user_id, program_owner;
                    END IF;
                END IF;
            END IF;

            -- Nested rather than ANDed with the table name: PL/pgSQL
            -- evaluates the whole boolean against the record type, so
            -- `TG_TABLE_NAME = 'x' AND NEW.only_on_x IS NOT NULL` raises
            -- "record new has no field" on every OTHER table the trigger
            -- is attached to. The nesting is what makes one function
            -- serve two tables with different columns.
            IF TG_TABLE_NAME = 'fitness_program_draft' THEN
                IF NEW.resulting_revision_id IS NOT NULL THEN
                    SELECT user_id INTO program_owner
                    FROM fitness_program_revision
                    WHERE id = NEW.resulting_revision_id;
                    IF program_owner IS DISTINCT FROM NEW.user_id THEN
                        RAISE EXCEPTION
                            'draft owner % cannot point at revision owned '
                            'by %', NEW.user_id, program_owner;
                    END IF;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("fitness_template_revision", "fitness_program_draft"):
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_owner ON {table};
            CREATE TRIGGER trg_{table}_owner
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION fitness_program_owner_matches()
        """)

    # ── An activated revision is frozen ────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_program_revision_frozen()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.activated_at IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.snapshot::text IS DISTINCT FROM OLD.snapshot::text
               OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
               OR NEW.revision IS DISTINCT FROM OLD.revision
               OR NEW.program_id IS DISTINCT FROM OLD.program_id
               OR NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version
               OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
               OR NEW.effect_scope IS DISTINCT FROM OLD.effect_scope THEN
                RAISE EXCEPTION
                    'revision % of program % is activated and frozen. A '
                    'logged session was performed from it and a review '
                    'cited it; editing it would rewrite what happened. '
                    'Create the next revision instead.',
                    OLD.revision, OLD.program_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_program_revision_frozen
            ON fitness_program_revision;
        CREATE TRIGGER trg_program_revision_frozen
        BEFORE UPDATE ON fitness_program_revision
        FOR EACH ROW EXECUTE FUNCTION fitness_program_revision_frozen()
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_template_revision_frozen()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.activated_at IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.snapshot::text IS DISTINCT FROM OLD.snapshot::text
               OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
               OR NEW.revision IS DISTINCT FROM OLD.revision THEN
                RAISE EXCEPTION
                    'revision % of template % is activated and frozen',
                    OLD.revision, OLD.template_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_template_revision_frozen
            ON fitness_template_revision;
        CREATE TRIGGER trg_template_revision_frozen
        BEFORE UPDATE ON fitness_template_revision
        FOR EACH ROW EXECUTE FUNCTION fitness_template_revision_frozen()
    """)

    # ── A decided draft keeps its decision ─────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_program_draft_terminal()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status NOT IN ('accepted', 'rejected') THEN
                RETURN NEW;
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               OR NEW.payload::text IS DISTINCT FROM OLD.payload::text
               OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
               OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
               OR NEW.resulting_revision_id
                  IS DISTINCT FROM OLD.resulting_revision_id THEN
                RAISE EXCEPTION
                    'draft % is already %; its decision is the audit trail '
                    'for the revision it produced. Create a new draft.',
                    OLD.id, OLD.status;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_program_draft_terminal
            ON fitness_program_draft;
        CREATE TRIGGER trg_program_draft_terminal
        BEFORE UPDATE ON fitness_program_draft
        FOR EACH ROW EXECUTE FUNCTION fitness_program_draft_terminal()
    """)

    # ── Templates carry their current revision ─────────────────────────
    # On `fitness_template` rather than in a join table: every reader of a
    # template needs to know which revision it is, and a nullable integer
    # beside the data cannot be forgotten the way a join can.
    op.execute("""
        ALTER TABLE fitness_template
        ADD COLUMN IF NOT EXISTS current_revision INTEGER
    """)
    op.execute("""
        ALTER TABLE fitness_phase
        ADD COLUMN IF NOT EXISTS program_revision INTEGER
    """)


def downgrade() -> None:
    """Drops the revision history.

    Note what this destroys: the record of what the plan was on the days
    already trained. The sessions remain, and they stop being attributable
    to a prescription. §7: never run a downgrade as a recovery step.
    """
    for table in ("fitness_program_draft", "fitness_template_revision",
                  "fitness_program_revision"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS fitness_program_owner_matches()")
    op.execute("DROP FUNCTION IF EXISTS fitness_program_revision_frozen()")
    op.execute("DROP FUNCTION IF EXISTS fitness_template_revision_frozen()")
    op.execute("DROP FUNCTION IF EXISTS fitness_program_draft_terminal()")
    op.execute(
        "ALTER TABLE fitness_template DROP COLUMN IF EXISTS current_revision"
    )
    op.execute(
        "ALTER TABLE fitness_phase DROP COLUMN IF EXISTS program_revision"
    )
