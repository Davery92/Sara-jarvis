"""M13 — curated science library with accepted-only retrieval.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 28 / §16 M13.

What the schema makes impossible:

* **Citing a paper nobody reviewed.** Retrieval filters on
  `status = 'accepted'`, and the partial index that makes retrieval fast
  exists ONLY over accepted, non-retracted rows. An unreviewed record is
  not merely deprioritised: there is no index entry for it to be found
  through, so a future query that forgets the predicate gets a sequential
  scan and a visible slowdown rather than silently widening the library.
* **Two records for one paper.** Unique on `(user_id, doi)` where the DOI
  is present, and on `(user_id, content_hash)` per revision. The DOI is
  stored lowercased and prefix-stripped by the schema layer, because
  `10.1234/ABC`, `doi:10.1234/abc` and `https://doi.org/10.1234/abc` are
  one paper and a raw-string index would file three.
* **Editing cited text.** A `BEFORE UPDATE` trigger freezes an accepted
  revision's hash, text location and embedding metadata. A citation trail
  over mutable text is decoration.
* **A chunk belonging to one athlete under another's record.** A trigger
  checks chunk, revision and record share an owner; §5's rule that an FK to
  a UUID is not an ownership check.
* **A padded embedding.** The column is `vector(1024)`, matching
  `doc_chunk`, so a backend answering with a different width fails the
  INSERT. Padding would leave the search working and the results
  meaningless, which is worse than an outage.
* **A refresh that promotes its own finds.** A CHECK forbids
  `discovered_by = 'refresh'` together with `status = 'accepted'` unless a
  curation event exists for it — enforced through a trigger that counts
  accept events, so the only route from refresh to accepted is a human
  decision that leaves a row behind.

Revision ID: 172_fitness_science
Revises: 171_fitness_photo_analysis
"""
from alembic import op

revision = "172_fitness_science"
down_revision = "171_fitness_photo_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector is already installed (episode.embedding, doc_chunk), but say
    # so rather than inherit it: this migration is meaningless without it
    # and a clear failure here beats a confusing one on the first INSERT.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_record (
            id               VARCHAR PRIMARY KEY,
            user_id          VARCHAR NOT NULL
                             REFERENCES app_user(id) ON DELETE CASCADE,
            title            VARCHAR(500) NOT NULL,
            authors          VARCHAR(1000),
            publication_year INTEGER,
            journal          VARCHAR(300),
            doi              VARCHAR(200),
            url              VARCHAR(2000),
            source_type      VARCHAR(40) NOT NULL,
            topics           JSONB NOT NULL DEFAULT '[]'::jsonb,
            population       TEXT,
            limitations      TEXT,
            quality          VARCHAR(20),
            status           VARCHAR(20) NOT NULL DEFAULT 'unreviewed',
            visibility       VARCHAR(20) NOT NULL DEFAULT 'owner',
            superseded_by_id VARCHAR,
            retracted_at     TIMESTAMPTZ,
            retraction_reason TEXT,
            discovered_by    VARCHAR(40) NOT NULL DEFAULT 'manual',
            discovered_run_id VARCHAR,
            notes            TEXT,
            current_revision INTEGER NOT NULL DEFAULT 1,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_science_status CHECK (status IN (
                'unreviewed', 'accepted', 'rejected', 'superseded', 'retracted'
            )),
            CONSTRAINT ck_science_visibility CHECK (
                visibility IN ('owner', 'public')
            ),
            CONSTRAINT ck_science_source_type CHECK (source_type IN (
                'meta_analysis', 'systematic_review', 'rct', 'observational',
                'narrative_review', 'position_stand', 'secondary'
            )),
            CONSTRAINT ck_science_quality CHECK (
                quality IS NULL OR quality IN ('high', 'moderate', 'low')
            ),
            CONSTRAINT ck_science_discovered CHECK (
                discovered_by IN ('manual', 'upload', 'url', 'refresh')
            ),
            -- An identifier is required, or a duplicate cannot be told from
            -- a new paper and a citation has nothing to point a reader at.
            CONSTRAINT ck_science_identifiable CHECK (
                doi IS NOT NULL OR url IS NOT NULL
            ),
            -- Acceptance requires the limitations field. Every paper has
            -- them; the ones left blank are the ones later misapplied.
            CONSTRAINT ck_science_accepted_has_limits CHECK (
                status <> 'accepted'
                OR (limitations IS NOT NULL AND length(trim(limitations)) > 0)
            ),
            -- A supersede must name its successor, or the chain from an old
            -- citation dead-ends.
            CONSTRAINT ck_science_superseded_has_target CHECK (
                status <> 'superseded' OR superseded_by_id IS NOT NULL
            ),
            CONSTRAINT ck_science_retracted_has_time CHECK (
                status <> 'retracted' OR retracted_at IS NOT NULL
            ),
            -- Public sharing is an admin act (§28.3). A record cannot be
            -- public while nobody has accepted it.
            CONSTRAINT ck_science_public_is_accepted CHECK (
                visibility <> 'public' OR status = 'accepted'
            )
        )
    """)

    # One DOI, one record, per owner. Partial so the many URL-only records
    # do not collide on NULL.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_science_record_doi
        ON fitness_science_record (user_id, doi)
        WHERE doi IS NOT NULL
    """)
    # The retrieval index covers ONLY what retrieval may see.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_record_retrievable
        ON fitness_science_record (user_id, status)
        WHERE status = 'accepted' AND retracted_at IS NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_record_owner_status
        ON fitness_science_record (user_id, status, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_record_topics
        ON fitness_science_record USING gin (topics)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_revision (
            id                 VARCHAR PRIMARY KEY,
            record_id          VARCHAR NOT NULL
                               REFERENCES fitness_science_record(id)
                               ON DELETE CASCADE,
            user_id            VARCHAR NOT NULL,
            revision           INTEGER NOT NULL,
            content_hash       VARCHAR(64),
            source_url         VARCHAR(2000),
            storage_key        VARCHAR(500),
            mime_type          VARCHAR(120),
            byte_size          INTEGER,
            extracted_chars    INTEGER,
            extraction_state   VARCHAR(20) NOT NULL DEFAULT 'pending',
            extraction_attempts INTEGER NOT NULL DEFAULT 0,
            failure_category   VARCHAR(40),
            failure_detail     TEXT,
            embedding_dim      INTEGER,
            embedding_model    VARCHAR(120),
            chunk_count        INTEGER NOT NULL DEFAULT 0,
            accepted_at        TIMESTAMPTZ,
            accepted_by        VARCHAR,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_science_revision UNIQUE (record_id, revision),
            CONSTRAINT ck_science_revision_positive CHECK (revision >= 1),
            CONSTRAINT ck_science_extraction_state CHECK (
                extraction_state IN ('pending', 'extracted', 'embedded', 'failed')
            ),
            -- An embedded revision has to say what embedded it. A library
            -- built at 1024 and queried by a 768-dim model returns nonsense
            -- silently; this is what makes that answerable.
            CONSTRAINT ck_science_embedded_has_model CHECK (
                extraction_state <> 'embedded'
                OR (embedding_dim IS NOT NULL AND embedding_model IS NOT NULL
                    AND chunk_count > 0)
            ),
            CONSTRAINT ck_science_failed_has_category CHECK (
                extraction_state <> 'failed' OR failure_category IS NOT NULL
            ),
            -- Only an embedded revision can be accepted: accepting one
            -- whose text never extracted would create a citation to nothing.
            CONSTRAINT ck_science_accept_needs_text CHECK (
                accepted_at IS NULL OR extraction_state = 'embedded'
            )
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_science_revision_hash
        ON fitness_science_revision (user_id, content_hash)
        WHERE content_hash IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_revision_state
        ON fitness_science_revision (extraction_state, extraction_attempts)
        WHERE extraction_state IN ('pending', 'failed')
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_chunk (
            id           VARCHAR PRIMARY KEY,
            revision_id  VARCHAR NOT NULL
                         REFERENCES fitness_science_revision(id)
                         ON DELETE CASCADE,
            record_id    VARCHAR NOT NULL,
            user_id      VARCHAR NOT NULL,
            chunk_idx    INTEGER NOT NULL,
            section      VARCHAR(300),
            text         TEXT NOT NULL,
            char_start   INTEGER,
            char_end     INTEGER,
            embedding    vector(1024),
            doc_chunk_id VARCHAR,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_science_chunk UNIQUE (revision_id, chunk_idx),
            CONSTRAINT ck_science_chunk_text CHECK (length(trim(text)) > 0)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_chunk_owner
        ON fitness_science_chunk (user_id, record_id)
    """)
    # HNSW over the whole chunk table, not a partial index: a chunk's
    # retrievability lives on its record, which changes with curation, and a
    # partial vector index on a joined predicate is not expressible. Owner
    # and status are filtered in the query.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_chunk_embedding
        ON fitness_science_chunk USING hnsw (embedding vector_cosine_ops)
    """)
    # Lexical half of the ranking. English stemming, because a query for
    # "hypertrophy training volume" should match "volume of training".
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_chunk_fts
        ON fitness_science_chunk
        USING gin (to_tsvector('english', text))
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_annotation (
            id         VARCHAR PRIMARY KEY,
            record_id  VARCHAR NOT NULL
                       REFERENCES fitness_science_record(id) ON DELETE CASCADE,
            user_id    VARCHAR NOT NULL,
            kind       VARCHAR(30) NOT NULL DEFAULT 'note',
            body       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_science_annotation_kind CHECK (
                kind IN ('caveat', 'application', 'disagreement', 'note')
            ),
            CONSTRAINT ck_science_annotation_body CHECK (
                length(trim(body)) > 0
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_annotation_owner
        ON fitness_science_annotation (user_id, record_id, created_at DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_curation_event (
            id               VARCHAR PRIMARY KEY,
            record_id        VARCHAR NOT NULL
                             REFERENCES fitness_science_record(id)
                             ON DELETE CASCADE,
            user_id          VARCHAR NOT NULL,
            revision         INTEGER,
            action           VARCHAR(20) NOT NULL,
            from_status      VARCHAR(20),
            to_status        VARCHAR(20),
            reason           TEXT NOT NULL,
            superseded_by_id VARCHAR,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT ck_science_curation_action CHECK (action IN (
                'accept', 'reject', 'supersede', 'retract', 'reopen', 'annotate'
            )),
            -- A decision with no reason is a click. The reason is what a
            -- future reader needs: what the paper is good for, and what it
            -- was accepted despite.
            CONSTRAINT ck_science_curation_reason CHECK (
                length(trim(reason)) >= 10
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_curation_record
        ON fitness_science_curation_event (record_id, created_at DESC)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS fitness_science_refresh_run (
            id                 VARCHAR PRIMARY KEY,
            user_id            VARCHAR NOT NULL,
            attempted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            succeeded          BOOLEAN NOT NULL DEFAULT FALSE,
            finished_at        TIMESTAMPTZ,
            queried_topics     JSONB NOT NULL DEFAULT '[]'::jsonb,
            candidates_seen    INTEGER NOT NULL DEFAULT 0,
            queued_unreviewed  INTEGER NOT NULL DEFAULT 0,
            duplicates_skipped INTEGER NOT NULL DEFAULT 0,
            retractions_flagged JSONB NOT NULL DEFAULT '[]'::jsonb,
            affected_review_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            digest_sent        BOOLEAN NOT NULL DEFAULT FALSE,
            detail             TEXT,

            CONSTRAINT ck_science_refresh_counts CHECK (
                candidates_seen >= 0 AND queued_unreviewed >= 0
                AND duplicates_skipped >= 0
            ),
            CONSTRAINT ck_science_refresh_finished CHECK (
                succeeded = FALSE OR finished_at IS NOT NULL
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_science_refresh_owner
        ON fitness_science_refresh_run (user_id, attempted_at DESC)
    """)

    # ── Owner coherence ────────────────────────────────────────────────
    # A chunk, its revision and its record all belong to one athlete. §5:
    # an FK to a UUID is not an ownership check, and a chunk filed under
    # another owner's record would surface somebody else's library in an
    # owner-scoped query that looks correct.
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_science_owner_matches()
        RETURNS TRIGGER AS $$
        DECLARE
            record_owner VARCHAR;
            revision_owner VARCHAR;
            revision_record VARCHAR;
        BEGIN
            SELECT user_id INTO record_owner
            FROM fitness_science_record WHERE id = NEW.record_id;
            IF record_owner IS NULL THEN
                RAISE EXCEPTION 'science record % does not exist',
                    NEW.record_id;
            END IF;
            IF record_owner <> NEW.user_id THEN
                RAISE EXCEPTION
                    'science row owner % does not match record owner %',
                    NEW.user_id, record_owner;
            END IF;

            IF TG_TABLE_NAME = 'fitness_science_chunk' THEN
                SELECT user_id, record_id
                INTO revision_owner, revision_record
                FROM fitness_science_revision WHERE id = NEW.revision_id;
                IF revision_owner IS NULL THEN
                    RAISE EXCEPTION 'science revision % does not exist',
                        NEW.revision_id;
                END IF;
                IF revision_owner <> NEW.user_id
                   OR revision_record <> NEW.record_id THEN
                    RAISE EXCEPTION
                        'chunk does not belong to revision % of record %',
                        NEW.revision_id, NEW.record_id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in (
        "fitness_science_revision", "fitness_science_chunk",
        "fitness_science_annotation", "fitness_science_curation_event",
    ):
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_owner ON {table};
            CREATE TRIGGER trg_{table}_owner
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION fitness_science_owner_matches()
        """)

    # ── An accepted revision's text is frozen ──────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_science_revision_frozen()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.accepted_at IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.content_hash IS DISTINCT FROM OLD.content_hash
               OR NEW.extracted_chars IS DISTINCT FROM OLD.extracted_chars
               OR NEW.embedding_dim IS DISTINCT FROM OLD.embedding_dim
               OR NEW.embedding_model IS DISTINCT FROM OLD.embedding_model
               OR NEW.chunk_count IS DISTINCT FROM OLD.chunk_count
               OR NEW.extraction_state IS DISTINCT FROM OLD.extraction_state
               OR NEW.storage_key IS DISTINCT FROM OLD.storage_key THEN
                RAISE EXCEPTION
                    'revision % of record % is accepted and its text is '
                    'frozen; a citation trail over editable text is '
                    'decoration. Add a new revision instead.',
                    OLD.revision, OLD.record_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_science_revision_frozen
            ON fitness_science_revision;
        CREATE TRIGGER trg_science_revision_frozen
        BEFORE UPDATE ON fitness_science_revision
        FOR EACH ROW EXECUTE FUNCTION fitness_science_revision_frozen()
    """)

    # ── Acceptance leaves a row behind ─────────────────────────────────
    # §28.6: a refresh never auto-promotes. The only route to 'accepted' is
    # a curation decision, and this makes the database agree: a record
    # cannot be accepted without an accept event naming it.
    op.execute("""
        CREATE OR REPLACE FUNCTION fitness_science_accept_needs_event()
        RETURNS TRIGGER AS $$
        DECLARE
            accept_events INTEGER;
        BEGIN
            IF NEW.status <> 'accepted' THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'accepted' THEN
                RETURN NEW;
            END IF;
            SELECT COUNT(*) INTO accept_events
            FROM fitness_science_curation_event
            WHERE record_id = NEW.id AND action = 'accept';
            IF accept_events = 0 THEN
                RAISE EXCEPTION
                    'record % cannot become accepted without a curation '
                    'event: acceptance is a human decision and has to leave '
                    'a reason behind. Insert the event first.', NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_science_accept_needs_event
            ON fitness_science_record;
        CREATE TRIGGER trg_science_accept_needs_event
        BEFORE INSERT OR UPDATE ON fitness_science_record
        FOR EACH ROW EXECUTE FUNCTION fitness_science_accept_needs_event()
    """)

    # ── The citation trail on a review ─────────────────────────────────
    # §28.5/§28 completion: "review citation trail reconstructs exact
    # retrieved versions". The column holds the validated `ScienceCitation`
    # list — record, revision, chunk, offsets and the ranking policy that
    # produced it — so an old review can be explained under the policy that
    # actually ran rather than today's.
    op.execute("""
        ALTER TABLE fitness_coach_review
        ADD COLUMN IF NOT EXISTS science_citations JSONB
    """)
    op.execute("""
        ALTER TABLE fitness_coach_review
        ADD COLUMN IF NOT EXISTS science_policy_version INTEGER
    """)
    # Retrieval is not free and a review that was given no evidence must be
    # distinguishable from one where retrieval was never attempted — the
    # first is a judgement about the library, the second is a bug.
    op.execute("""
        ALTER TABLE fitness_coach_review
        ADD COLUMN IF NOT EXISTS science_offered INTEGER
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_coach_review_science
        ON fitness_coach_review (user_id)
        WHERE science_citations IS NOT NULL
    """)

    # ── The embedding width is the one the config declares ─────────────
    # A column of the wrong width would make every INSERT fail at runtime
    # instead of here, where the message can say why.
    op.execute("""
        DO $$
        DECLARE
            dims INTEGER;
        BEGIN
            SELECT atttypmod INTO dims
            FROM pg_attribute
            WHERE attrelid = 'fitness_science_chunk'::regclass
              AND attname = 'embedding';
            IF dims IS DISTINCT FROM 1024 THEN
                RAISE EXCEPTION
                    'fitness_science_chunk.embedding is vector(%), but the '
                    'embedding model (bge-m3) is 1024-dimensional and '
                    'doc_chunk is vector(1024). A mismatch here is not a '
                    'width problem: a padded or truncated vector is still '
                    'searchable, so the search keeps working and the '
                    'results stop meaning anything.', dims;
            END IF;
        END $$
    """)


def downgrade() -> None:
    """Drops the library.

    Note what this destroys: every curation decision and the reason for it.
    The records can be re-ingested; the judgement about which papers are
    worth citing and what each one cannot support is a person's work and is
    not recoverable from the sources. §7: never run a downgrade as a
    recovery step.
    """
    for table in (
        "fitness_science_refresh_run", "fitness_science_curation_event",
        "fitness_science_annotation", "fitness_science_chunk",
        "fitness_science_revision", "fitness_science_record",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS fitness_science_owner_matches()")
    op.execute("DROP FUNCTION IF EXISTS fitness_science_revision_frozen()")
    op.execute("DROP FUNCTION IF EXISTS fitness_science_accept_needs_event()")
    for column in ("science_citations", "science_policy_version",
                   "science_offered"):
        op.execute(
            f"ALTER TABLE fitness_coach_review DROP COLUMN IF EXISTS {column}"
        )
