"""Step 28 of FITNESS_COACH_IMPLEMENTATION_PLAN: the curated library.

A retrieval system is easy to build wrongly in a way that looks right.
Similarity search over a pile of PDFs returns plausible paragraphs for any
query, and a coach quoting them sounds well-read. These tests are about the
four rules that keep it from being that:

* **Ingestion is not acceptance.** An unreviewed record with a perfect
  similarity score does not appear in retrieval.
* **A citation names a chunk of a revision**, so the exact text survives the
  publisher replacing the PDF.
* **Population is recorded, never inferred**, and a mismatch is visible
  rather than averaged away.
* **A citation is only valid if it was offered**, because a model asked to
  cite its sources produces real-looking ids for papers it never saw.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_science_pg.py
"""
import asyncio
import hashlib
import json
import os
import uuid
from typing import List, Optional

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

DIM = 1024


def _vector(seed: float = 0.1) -> List[float]:
    """A deterministic unit-ish vector of the right width.

    The width is the point: a test that embedded to 8 dimensions would pass
    against a column that cannot hold what production produces.
    """
    return [seed] * DIM


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"s28a-{uuid.uuid4().hex[:17]}"
    bob = f"s28b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s28.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_science_chunk", "fitness_science_curation_event",
                  "fitness_science_annotation", "fitness_science_revision",
                  "fitness_science_record", "fitness_science_refresh_run",
                  "fitness_athlete_profile"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
            pg.commit()
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _record(
    pg, user_id, *, title="Training volume and hypertrophy",
    status="unreviewed", doi=None, url="https://example.invalid/paper",
    source_type="rct", topics=("hypertrophy",), population=None,
    limitations=None, quality=None, text_body="Higher weekly set volume "
    "produced greater muscle thickness in resistance-trained men over "
    "twelve weeks of supervised training.",
    accepted=False, discovered_by="manual", seed=0.1,
):
    """One record with one embedded revision and one chunk.

    Inserted directly rather than through `register_source` so the tests of
    retrieval do not depend on an embedding backend; the ingestion path has
    its own tests below with the backend stubbed.
    """
    record_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    pg.execute(text("""
        INSERT INTO fitness_science_record (
            id, user_id, title, doi, url, source_type, topics, population,
            limitations, quality, status, discovered_by, current_revision
        ) VALUES (
            :id, :u, :title, :doi, :url, :st, CAST(:topics AS JSONB),
            :population, :limitations, :quality, 'unreviewed',
            :discovered_by, 1
        )
    """), {
        "id": record_id, "u": user_id, "title": title, "doi": doi,
        "url": url, "st": source_type,
        "topics": json.dumps(list(topics)), "population": population,
        "limitations": limitations, "quality": quality,
        "discovered_by": discovered_by,
    })
    pg.execute(text("""
        INSERT INTO fitness_science_revision (
            id, record_id, user_id, revision, content_hash, extraction_state,
            extracted_chars, embedding_dim, embedding_model, chunk_count,
            accepted_at
        ) VALUES (
            :id, :r, :u, 1, :hash, 'embedded', :chars, 1024, 'bge-m3', 1,
            CASE WHEN :accepted THEN NOW() ELSE NULL END
        )
    """), {
        "id": revision_id, "r": record_id, "u": user_id,
        # A nonce, because two records in one test can legitimately hold
        # the same text — the hash uniqueness is the production dedup and
        # has its own test.
        "hash": hashlib.sha256(
            (title + text_body + record_id).encode()
        ).hexdigest(),
        "chars": len(text_body), "accepted": accepted or status == "accepted",
    })
    pg.execute(text("""
        INSERT INTO fitness_science_chunk (
            id, revision_id, record_id, user_id, chunk_idx, section, text,
            char_start, char_end, embedding
        ) VALUES (
            :id, :rev, :r, :u, 0, 'Results', :text, 0, :end,
            CAST(:embedding AS vector)
        )
    """), {
        "id": chunk_id, "rev": revision_id, "r": record_id, "u": user_id,
        "text": text_body, "end": len(text_body),
        "embedding": "[" + ",".join(f"{v:.6f}" for v in _vector(seed)) + "]",
    })

    if status == "accepted":
        # Acceptance needs a curation event: the trigger enforces it, which
        # is also the point of the next test.
        pg.execute(text("""
            INSERT INTO fitness_science_curation_event
                (id, record_id, user_id, revision, action, from_status,
                 to_status, reason)
            VALUES (:id, :r, :u, 1, 'accept', 'unreviewed', 'accepted',
                    'read it; the volume gradient is the usable finding')
        """), {"id": str(uuid.uuid4()), "r": record_id, "u": user_id})
        pg.execute(text("""
            UPDATE fitness_science_record
            SET status = 'accepted',
                limitations = COALESCE(:limits, 'trained men only')
            WHERE id = :id
        """), {"id": record_id, "limits": limitations})
        pg.execute(text("""
            UPDATE fitness_science_revision SET accepted_at = NOW()
            WHERE id = :id
        """), {"id": revision_id})
    elif status != "unreviewed":
        pg.execute(text("""
            UPDATE fitness_science_record SET
                status = CAST(:s AS VARCHAR),
                retracted_at = CASE WHEN CAST(:s AS VARCHAR) = 'retracted'
                    THEN NOW() END,
                superseded_by_id = CASE WHEN CAST(:s AS VARCHAR) = 'superseded'
                    THEN CAST(:self AS VARCHAR) END
            WHERE id = :id
        """), {"s": status, "id": record_id, "self": record_id})

    pg.commit()
    return record_id, revision_id, chunk_id


# ─────────────────────────────────────────────────────────────────────────
# The migration
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_embedding_column_is_the_configured_width(pg):
    """§28.1: verify dim=1024 matches the config.

    A library built at one width and queried by a model of another returns
    confident nonsense, silently. This is the check that makes it loud.
    """
    from app.core.config import settings

    dims = pg.execute(text("""
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'fitness_science_chunk'::regclass
          AND attname = 'embedding'
    """)).scalar()
    assert dims == 1024
    assert settings.embedding_dim == 1024

    doc_dims = pg.execute(text("""
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'doc_chunk'::regclass AND attname = 'embedding'
    """)).scalar()
    assert dims == doc_dims, (
        "the science library and the document store must embed at the same "
        "width, or one model cannot serve both"
    )


@requires_pg
def test_a_vector_of_the_wrong_width_is_rejected_by_the_column(pg, two_athletes):
    """Padding would leave the search working and the results meaningless,
    which is strictly worse than an error."""
    alice, _ = two_athletes
    record_id, revision_id, _ = _record(pg, alice)
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_science_chunk (
                id, revision_id, record_id, user_id, chunk_idx, text, embedding
            ) VALUES (:id, :rev, :r, :u, 99, 'short',
                      CAST(:embedding AS vector))
        """), {
            "id": str(uuid.uuid4()), "rev": revision_id, "r": record_id,
            "u": alice, "embedding": "[" + ",".join(["0.1"] * 768) + "]",
        })
        pg.commit()
    pg.rollback()


@requires_pg
def test_the_retrieval_index_covers_only_accepted_rows(pg):
    """An unreviewed record is not merely deprioritised: there is no index
    entry for it, so a query that forgets the predicate gets slow rather
    than quietly widening the library."""
    definition = pg.execute(text("""
        SELECT indexdef FROM pg_indexes
        WHERE indexname = 'ix_science_record_retrievable'
    """)).scalar()
    assert definition is not None
    # Postgres normalises the predicate it stores, so match its spelling
    # rather than the one in the migration.
    assert "'accepted'::text" in definition
    assert "retracted_at IS NULL" in definition


@requires_pg
def test_the_vector_and_lexical_indexes_both_exist(pg):
    """Hybrid ranking needs both. A missing HNSW index makes retrieval a
    sequential scan over every chunk, which works and then stops working
    at a few thousand papers."""
    names = {
        row[0] for row in pg.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'fitness_science_chunk'
        """)).fetchall()
    }
    assert "ix_science_chunk_embedding" in names
    assert "ix_science_chunk_fts" in names


# ─────────────────────────────────────────────────────────────────────────
# Acceptance is a decision, and it leaves a row
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_record_cannot_become_accepted_without_a_curation_event(
    pg, two_athletes,
):
    """§28.6's guarantee, enforced by the database rather than promised by
    a comment: the only route to `accepted` runs through a person."""
    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice, limitations="trained men only")
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        pg.execute(text("""
            UPDATE fitness_science_record SET status = 'accepted'
            WHERE id = :id
        """), {"id": record_id})
        pg.commit()
    assert "curation event" in str(excinfo.value)
    pg.rollback()


@requires_pg
def test_acceptance_requires_the_limitations_field(pg, two_athletes):
    """Every paper has limitations, and the ones left blank are the ones
    later misapplied."""
    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice)
    pg.execute(text("""
        INSERT INTO fitness_science_curation_event
            (id, record_id, user_id, revision, action, reason)
        VALUES (:id, :r, :u, 1, 'accept', 'looks good to me, accepting it')
    """), {"id": str(uuid.uuid4()), "r": record_id, "u": alice})
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            UPDATE fitness_science_record
            SET status = 'accepted', limitations = NULL WHERE id = :id
        """), {"id": record_id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_curation_decision_needs_a_reason(pg, two_athletes):
    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice)
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_science_curation_event
                (id, record_id, user_id, revision, action, reason)
            VALUES (:id, :r, :u, 1, 'accept', 'ok')
        """), {"id": str(uuid.uuid4()), "r": record_id, "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_curation_records_the_transition_and_preserves_history(
    pg, two_athletes,
):
    """§28.3: rejected, superseded and retracted versions are preserved.
    An old review cited this text and that citation has to resolve."""
    from app.schemas.fitness_coach import (
        CurationAction, EvidenceQuality, ScienceCurationInput,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice)

    accepted = science.curate(pg, alice, record_id, ScienceCurationInput(
        action=CurationAction.ACCEPT, revision=1,
        reason="the volume gradient is the usable finding here",
        limitations="resistance-trained men only, twelve weeks",
        quality=EvidenceQuality.MODERATE,
    ))
    assert accepted["from_status"] == "unreviewed"
    assert accepted["to_status"] == "accepted"

    successor_id, _, _ = _record(
        pg, alice, title="A larger replication", doi="10.9999/newer",
    )
    superseded = science.curate(pg, alice, record_id, ScienceCurationInput(
        action=CurationAction.SUPERSEDE, revision=1,
        superseded_by_id=successor_id,
        reason="the larger replication covers the same question better",
    ))
    assert superseded["to_status"] == "superseded"

    history = science.history(pg, alice, record_id)
    assert [event["action"] for event in history] == ["accept", "supersede"]
    assert history[0]["reason"].startswith("the volume gradient")
    # The record and its text are still there.
    row = pg.execute(text("""
        SELECT status, superseded_by_id, limitations
        FROM fitness_science_record WHERE id = :id
    """), {"id": record_id}).fetchone()
    assert row.status == "superseded"
    assert row.superseded_by_id == successor_id
    assert "twelve weeks" in row.limitations


@requires_pg
def test_an_undefined_transition_is_refused_with_the_allowed_set(
    pg, two_athletes,
):
    """A bare conflict makes a client retry blindly, which is how a reject
    becomes an accept."""
    from app.schemas.fitness_coach import CurationAction, ScienceCurationInput
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice, status="retracted")
    with pytest.raises(science.CurationConflict) as excinfo:
        science.curate(pg, alice, record_id, ScienceCurationInput(
            action=CurationAction.REOPEN, revision=1,
            reason="I think the retraction was unfair to the authors",
        ))
    message = str(excinfo.value)
    assert "retracted" in message
    assert "Allowed: none" in message


@requires_pg
def test_curating_a_stale_revision_is_refused(pg, two_athletes):
    """Accepting blind would accept text nobody looked at."""
    from app.schemas.fitness_coach import CurationAction, ScienceCurationInput
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice)
    pg.execute(text("""
        UPDATE fitness_science_record SET current_revision = 2
        WHERE id = :id
    """), {"id": record_id})
    pg.commit()
    with pytest.raises(science.CurationConflict) as excinfo:
        science.curate(pg, alice, record_id, ScienceCurationInput(
            action=CurationAction.ACCEPT, revision=1,
            reason="accepting the version I read last week",
            limitations="trained men",
        ))
    assert "revision 2" in str(excinfo.value)


@requires_pg
def test_an_accepted_revisions_text_cannot_be_edited(pg, two_athletes):
    """A citation trail over mutable text is decoration."""
    alice, _ = two_athletes
    _, revision_id, _ = _record(pg, alice, status="accepted")
    for column, value in (
        ("content_hash", "'0' || repeat('a', 63)"),
        ("extracted_chars", "99"),
        ("chunk_count", "42"),
        ("extraction_state", "'pending'"),
    ):
        with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
            pg.execute(text(
                f"UPDATE fitness_science_revision SET {column} = {value} "
                f"WHERE id = :id"
            ), {"id": revision_id})
            pg.commit()
        assert "frozen" in str(excinfo.value)
        pg.rollback()


@requires_pg
def test_a_record_cannot_supersede_itself(pg, two_athletes):
    from app.schemas.fitness_coach import CurationAction, ScienceCurationInput
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice)
    with pytest.raises(science.CurationConflict):
        science.curate(pg, alice, record_id, ScienceCurationInput(
            action=CurationAction.SUPERSEDE, revision=1,
            superseded_by_id=record_id,
            reason="this newer version of itself is better somehow",
        ))


# ─────────────────────────────────────────────────────────────────────────
# Retrieval: accepted-only, owner-scoped
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def stub_embeddings(monkeypatch):
    """A deterministic embedding backend.

    Retrieval tests must not depend on the GPU host: a test that silently
    skips when `her` is down is a test that is not there on the day it
    matters.
    """
    from app.services import embeddings as facade

    async def one(text_value, capability="embedding"):
        return _vector(0.1)

    async def batch(texts, capability="embedding"):
        return [_vector(0.1) for _ in texts]

    monkeypatch.setattr(facade, "get_embedding", one)
    monkeypatch.setattr(facade, "get_embeddings_batch", batch)
    return facade


@requires_pg
def test_an_unreviewed_record_is_never_retrieved(
    pg, two_athletes, stub_embeddings,
):
    """The whole design. Similarity measures wording; endorsement is a
    decision somebody made, and an identical-text unreviewed record scoring
    perfectly must still not appear."""
    from app.services.fitness import science

    alice, _ = two_athletes
    body = "Higher weekly set volume produced greater muscle thickness."
    _record(pg, alice, status="unreviewed", text_body=body,
            url="https://example.invalid/unreviewed")

    hits = asyncio.run(science.search(pg, alice, "weekly set volume"))
    assert hits == []

    _record(pg, alice, status="accepted", text_body=body,
            url="https://example.invalid/accepted",
            limitations="trained men only")
    hits = asyncio.run(science.search(pg, alice, "weekly set volume"))
    assert len(hits) == 1
    assert hits[0].limitations == "trained men only"


@requires_pg
@pytest.mark.parametrize("status", ["rejected", "retracted", "superseded"])
def test_only_accepted_status_is_retrievable(
    pg, two_athletes, stub_embeddings, status,
):
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status=status)
    assert asyncio.run(science.search(pg, alice, "muscle thickness")) == []


@requires_pg
def test_a_retracted_record_disappears_from_retrieval_immediately(
    pg, two_athletes, stub_embeddings,
):
    """A withdrawn paper must stop being evidence the moment it is marked,
    without a reindex step somebody could forget."""
    from app.schemas.fitness_coach import CurationAction, ScienceCurationInput
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, _ = _record(pg, alice, status="accepted")
    assert len(asyncio.run(science.search(pg, alice, "muscle thickness"))) == 1

    science.curate(pg, alice, record_id, ScienceCurationInput(
        action=CurationAction.RETRACT, revision=1,
        reason="the journal withdrew it for data irregularities",
    ))
    assert asyncio.run(science.search(pg, alice, "muscle thickness")) == []


@requires_pg
def test_one_athlete_never_retrieves_anothers_library(
    pg, two_athletes, stub_embeddings,
):
    """§28.4: "same subject query cannot retrieve another athlete's private
    annotations/docs"."""
    from app.services.fitness import science

    alice, bob = two_athletes
    _record(pg, alice, status="accepted", title="Alice's accepted paper")

    assert asyncio.run(science.search(pg, bob, "muscle thickness")) == []
    mine = asyncio.run(science.search(pg, alice, "muscle thickness"))
    assert len(mine) == 1
    assert mine[0].title == "Alice's accepted paper"


@requires_pg
def test_a_private_annotation_is_not_visible_to_another_athlete(
    pg, two_athletes,
):
    from app.schemas.fitness_coach import ScienceAnnotationKind
    from app.services.fitness import science

    alice, bob = two_athletes
    record_id, _, _ = _record(pg, alice, status="accepted")
    science.annotate(
        pg, alice, record_id, ScienceAnnotationKind.CAVEAT,
        "everyone cites this for X and it does not say X",
    )

    mine = science.library(pg, alice)
    assert mine[0]["annotations"] == 1
    # Bob cannot see the record at all, let alone the note.
    assert science.library(pg, bob) == []
    with pytest.raises(LookupError):
        science.annotate(
            pg, bob, record_id, ScienceAnnotationKind.NOTE, "mine now",
        )


@requires_pg
def test_a_chunk_cannot_be_filed_under_another_owners_record(
    pg, two_athletes,
):
    """§5: an FK to a UUID is not an ownership check."""
    alice, bob = two_athletes
    record_id, revision_id, _ = _record(pg, alice)
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        pg.execute(text("""
            INSERT INTO fitness_science_chunk (
                id, revision_id, record_id, user_id, chunk_idx, text, embedding
            ) VALUES (:id, :rev, :r, :u, 5, 'text', CAST(:e AS vector))
        """), {
            "id": str(uuid.uuid4()), "rev": revision_id, "r": record_id,
            "u": bob,
            "e": "[" + ",".join(f"{v:.6f}" for v in _vector()) + "]",
        })
        pg.commit()
    assert "owner" in str(excinfo.value)
    pg.rollback()


@requires_pg
def test_retrieval_exposes_what_is_needed_to_judge_a_hit(
    pg, two_athletes, stub_embeddings,
):
    """§28.4: DOI/URL/population/limitations/chunk source location.

    A snippet with no population is how "trained men gained more from
    higher volume" becomes advice for a 52-year-old beginner."""
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted", doi="10.1234/vol",
        url="https://example.invalid/vol", source_type="meta_analysis",
        population="n=43 resistance-trained men, 18-35",
        limitations="no women; twelve weeks only", quality="high",
    )
    hit = asyncio.run(science.search(pg, alice, "muscle thickness"))[0]
    assert hit.doi == "10.1234/vol"
    assert hit.url == "https://example.invalid/vol"
    assert hit.population.startswith("n=43")
    assert "no women" in hit.limitations
    assert hit.section == "Results"
    assert hit.char_start == 0 and hit.char_end > 0
    assert hit.chunk_id and hit.revision == 1
    # The component scores stay separate, so "why was this shown" is
    # answerable rather than a single blended number.
    assert hit.similarity is not None
    assert hit.quality_weight == 1.0
    assert hit.ranking_policy_version == science.SCIENCE_RANKING_POLICY_VERSION


@requires_pg
def test_a_population_mismatch_is_scored_down_and_named(
    pg, two_athletes, stub_embeddings,
):
    """§28.4: ranking with population mismatch. Never silently dropped — a
    mismatch the coach can see beats a result that quietly vanished."""
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted", title="Trained men, high volume",
        url="https://example.invalid/trained",
        population="resistance-trained men with five years of experience",
        limitations="trained men only",
    )
    _record(
        pg, alice, status="accepted", title="Untrained novices, any volume",
        url="https://example.invalid/untrained",
        population="untrained novice participants, previously sedentary",
        limitations="novices only",
    )

    novice = science.AthleteContext(training_level="beginner", sex="male")
    hits = asyncio.run(science.search(
        pg, alice, "training volume for growth", athlete=novice,
    ))
    by_title = {hit.title: hit for hit in hits}
    assert by_title["Untrained novices, any volume"].applicability > 0
    mismatched = by_title["Trained men, high volume"]
    assert mismatched.applicability < 0
    assert "trained" in (mismatched.applicability_note or "")
    # Still returned, and ranked below the matching one.
    assert hits[0].title == "Untrained novices, any volume"


@requires_pg
def test_an_unrecorded_population_says_so_rather_than_scoring_as_a_match(
    pg, two_athletes, stub_embeddings,
):
    """Unknown is not the same as matching, and treating it as one is how a
    finding drifts onto the wrong person."""
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status="accepted", population=None)
    hit = asyncio.run(science.search(
        pg, alice, "muscle thickness",
        athlete=science.AthleteContext(training_level="advanced"),
    ))[0]
    assert hit.applicability == 0.0
    assert "not recorded" in (hit.applicability_note or "")


@requires_pg
def test_a_recorded_quality_grade_beats_the_source_type_default(
    pg, two_athletes, stub_embeddings,
):
    """A badly run RCT is worse evidence than a careful meta-analysis, and
    that judgement is the curator's, not a lookup table's."""
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted", title="A weak RCT", source_type="rct",
        quality="low", url="https://example.invalid/weak",
    )
    hit = asyncio.run(science.search(pg, alice, "muscle thickness"))[0]
    assert hit.quality_weight == science.QUALITY_WEIGHT[
        science.EvidenceQuality.LOW
    ]
    assert hit.quality_weight < science.TYPE_WEIGHT[science.SourceType.RCT]


@requires_pg
def test_an_ungraded_record_falls_back_to_its_source_type(
    pg, two_athletes, stub_embeddings,
):
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted", source_type="meta_analysis",
        quality=None, url="https://example.invalid/meta",
    )
    hit = asyncio.run(science.search(pg, alice, "muscle thickness"))[0]
    assert hit.quality is None
    assert hit.quality_weight == science.TYPE_WEIGHT[
        science.SourceType.META_ANALYSIS
    ]


@requires_pg
def test_a_topic_filter_scopes_retrieval(pg, two_athletes, stub_embeddings):
    from app.schemas.fitness_coach import ScienceTopic
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status="accepted", title="Sleep and strength",
            topics=("sleep",), url="https://example.invalid/sleep")
    _record(pg, alice, status="accepted", title="Volume and growth",
            topics=("hypertrophy",), url="https://example.invalid/vol")

    sleep_only = asyncio.run(science.search(
        pg, alice, "strength performance", topics=[ScienceTopic.SLEEP],
    ))
    assert [hit.title for hit in sleep_only] == ["Sleep and strength"]
    assert sleep_only[0].topic_match == 1.0


@requires_pg
def test_one_passage_per_record_in_the_result(
    pg, two_athletes, stub_embeddings,
):
    """Three paragraphs of one paper read as three sources, which is the
    quiet way a single study becomes "the literature"."""
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, revision_id, _ = _record(pg, alice, status="accepted")
    for index in (1, 2, 3):
        pg.execute(text("""
            INSERT INTO fitness_science_chunk (
                id, revision_id, record_id, user_id, chunk_idx, section,
                text, embedding
            ) VALUES (:id, :rev, :r, :u, :idx, 'Discussion', :text,
                      CAST(:e AS vector))
        """), {
            "id": str(uuid.uuid4()), "rev": revision_id, "r": record_id,
            "u": alice, "idx": index,
            "text": f"Another paragraph about muscle thickness, {index}.",
            "e": "[" + ",".join(f"{v:.6f}" for v in _vector(0.1)) + "]",
        })
    pg.commit()

    hits = asyncio.run(science.search(pg, alice, "muscle thickness", limit=5))
    assert len(hits) == 1


@requires_pg
def test_retrieval_falls_back_to_lexical_when_embeddings_are_down(
    pg, two_athletes, monkeypatch,
):
    """A library that cannot be searched when the GPU host is down is a
    library that is not there when it is most likely to be asked for."""
    from app.services import embeddings as facade
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted",
        text_body="Creatine monohydrate supplementation increased lean mass.",
    )

    async def unavailable(text_value, capability="embedding"):
        raise facade.EmbeddingUnavailable("the GPU host is down")

    monkeypatch.setattr(facade, "get_embedding", unavailable)
    hits = asyncio.run(science.search(pg, alice, "creatine monohydrate"))
    assert len(hits) == 1
    # And it says the similarity is unknown rather than reporting zero.
    assert hits[0].similarity is None
    assert hits[0].lexical > 0


@requires_pg
def test_a_query_embedding_of_the_wrong_width_is_refused(
    pg, two_athletes, monkeypatch,
):
    """Comparing a 768-dim query against a 1024-dim library would return
    confident nonsense."""
    from app.services import embeddings as facade
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status="accepted")

    async def narrow(text_value, capability="embedding"):
        return [0.1] * 768

    monkeypatch.setattr(facade, "get_embedding", narrow)
    with pytest.raises(science.ScienceError) as excinfo:
        asyncio.run(science.search(pg, alice, "muscle thickness"))
    assert excinfo.value.category.value == "embedding_dim_mismatch"


# ─────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_registered_paper_arrives_unreviewed(pg, two_athletes, stub_embeddings):
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    body = (
        "Abstract\nWe examined weekly set volume. Methods\nForty-three "
        "resistance-trained men completed twelve weeks. Results\nMuscle "
        "thickness increased more in the higher-volume group. Discussion\n"
        "The gradient was dose-dependent across the range studied."
    ) * 3
    result = asyncio.run(science.register_source(
        pg, alice,
        ScienceRegisterInput(
            title="Weekly set volume and hypertrophy",
            source_type=SourceType.RCT, topics=[ScienceTopic.HYPERTROPHY],
            doi="10.1234/Volume.2026",
            population="n=43 resistance-trained men",
        ),
        content=body.encode(), mime_type="text/plain", filename="paper.txt",
    ))
    assert result.status.value == "unreviewed"
    assert result.chunk_count >= 1
    assert result.extraction_state == "embedded"

    row = pg.execute(text("""
        SELECT status, doi, discovered_by FROM fitness_science_record
        WHERE id = :id
    """), {"id": result.record_id}).fetchone()
    assert row.status == "unreviewed"
    # The DOI is normalised, so the unique index actually collides.
    assert row.doi == "10.1234/volume.2026"
    # And it is not retrievable yet.
    assert asyncio.run(science.search(pg, alice, "weekly set volume")) == []


@requires_pg
@pytest.mark.parametrize("doi_input,expected", [
    ("10.1234/abc", "10.1234/abc"),
    ("doi:10.1234/abc", "10.1234/abc"),
    ("https://doi.org/10.1234/ABC", "10.1234/abc"),
    ("  10.1234/abc.  ", "10.1234/abc"),
])
def test_doi_forms_normalise_to_one_identifier(doi_input, expected):
    """Four spellings of one paper. A dedup check on the raw string would
    file four copies."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )

    payload = ScienceRegisterInput(
        title="A paper", source_type=SourceType.RCT,
        topics=[ScienceTopic.STRENGTH], doi=doi_input,
    )
    assert payload.doi == expected


def test_a_url_in_the_doi_field_is_rejected_with_a_hint():
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )

    with pytest.raises(Exception) as excinfo:
        ScienceRegisterInput(
            title="A paper", source_type=SourceType.RCT,
            topics=[ScienceTopic.STRENGTH],
            doi="https://example.invalid/paper",
        )
    assert "pass it as `url`" in str(excinfo.value)


def test_a_record_with_no_identifier_is_refused():
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )

    with pytest.raises(Exception) as excinfo:
        ScienceRegisterInput(
            title="A paper", source_type=SourceType.RCT,
            topics=[ScienceTopic.STRENGTH],
        )
    assert "needs a DOI or a URL" in str(excinfo.value)


@requires_pg
def test_the_same_doi_is_a_duplicate_not_a_second_record(
    pg, two_athletes, stub_embeddings,
):
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    body = ("Methods\nA study of protein intake. " * 30)
    payload = ScienceRegisterInput(
        title="Protein intake", source_type=SourceType.META_ANALYSIS,
        topics=[ScienceTopic.NUTRITION], doi="10.5555/protein",
    )
    first = asyncio.run(science.register_source(
        pg, alice, payload, content=body.encode(), mime_type="text/plain",
    ))
    second = asyncio.run(science.register_source(
        pg, alice, payload, content=body.encode(), mime_type="text/plain",
    ))
    assert second.duplicate_of == first.record_id
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_record WHERE user_id = :u
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_identical_text_under_a_different_doi_is_a_duplicate(
    pg, two_athletes, stub_embeddings,
):
    """A preprint and its published version. The checksum catches what the
    DOI cannot."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    body = ("Results\nSleep extension improved bench press velocity. " * 30)
    first = asyncio.run(science.register_source(
        pg, alice,
        ScienceRegisterInput(
            title="Sleep extension (preprint)", source_type=SourceType.RCT,
            topics=[ScienceTopic.SLEEP], doi="10.1111/preprint",
        ),
        content=body.encode(), mime_type="text/plain",
    ))
    second = asyncio.run(science.register_source(
        pg, alice,
        ScienceRegisterInput(
            title="Sleep extension (published)", source_type=SourceType.RCT,
            topics=[ScienceTopic.SLEEP], doi="10.1111/published",
        ),
        content=body.encode(), mime_type="text/plain",
    ))
    assert second.duplicate_of == first.record_id
    assert "preprint" in (second.detail or "")


@requires_pg
def test_a_scanned_pdf_with_no_text_layer_is_refused(pg, two_athletes):
    """Storing it would create a record that can be cited and contains
    nothing."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    with pytest.raises(science.ScienceError) as excinfo:
        asyncio.run(science.register_source(
            pg, alice,
            ScienceRegisterInput(
                title="A scan", source_type=SourceType.RCT,
                topics=[ScienceTopic.STRENGTH], doi="10.2222/scan",
            ),
            content=b"tiny", mime_type="text/plain",
        ))
    assert excinfo.value.category.value == "no_text"
    assert "no text layer" in str(excinfo.value)
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_record WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_an_unsupported_type_is_refused_by_category(pg, two_athletes):
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    with pytest.raises(science.ScienceError) as excinfo:
        asyncio.run(science.register_source(
            pg, alice,
            ScienceRegisterInput(
                title="A spreadsheet", source_type=SourceType.SECONDARY,
                topics=[ScienceTopic.NUTRITION], doi="10.3333/xls",
            ),
            content=b"x" * 500, mime_type="application/vnd.ms-excel",
        ))
    assert excinfo.value.category.value == "unsupported_type"


@requires_pg
def test_an_unavailable_embedding_backend_stores_nothing(pg, two_athletes, monkeypatch):
    """§28.1: never fabricate or pad. A chunk with no vector is invisible to
    retrieval while looking present in the library."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services import embeddings as facade
    from app.services.fitness import science

    alice, _ = two_athletes

    async def unavailable(texts, capability="embedding"):
        raise facade.EmbeddingUnavailable("the GPU host is down")

    monkeypatch.setattr(facade, "get_embeddings_batch", unavailable)
    with pytest.raises(science.ScienceError) as excinfo:
        asyncio.run(science.register_source(
            pg, alice,
            ScienceRegisterInput(
                title="A paper", source_type=SourceType.RCT,
                topics=[ScienceTopic.STRENGTH], doi="10.4444/paper",
            ),
            content=("Methods\nA study. " * 40).encode(),
            mime_type="text/plain",
        ))
    assert excinfo.value.category.value == "embedding_unavailable"
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_science_chunk WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_a_wrong_width_embedding_refuses_rather_than_padding(
    pg, two_athletes, monkeypatch,
):
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services import embeddings as facade
    from app.services.fitness import science

    alice, _ = two_athletes

    async def narrow(texts, capability="embedding"):
        return [[0.1] * 768 for _ in texts]

    monkeypatch.setattr(facade, "get_embeddings_batch", narrow)
    with pytest.raises(science.ScienceError) as excinfo:
        asyncio.run(science.register_source(
            pg, alice,
            ScienceRegisterInput(
                title="A paper", source_type=SourceType.RCT,
                topics=[ScienceTopic.STRENGTH], doi="10.6666/paper",
            ),
            content=("Methods\nA study. " * 40).encode(),
            mime_type="text/plain",
        ))
    assert excinfo.value.category.value == "embedding_dim_mismatch"
    assert "Padding or truncating" in str(excinfo.value)


@requires_pg
def test_research_text_does_not_reach_the_personal_document_store(
    pg, two_athletes, stub_embeddings,
):
    """§28.2: do not send research documents into personal memory or PKG
    extraction. `doc_chunk` is what the chat document tools search — a paper
    in there means a question about David's own notes retrieving a study."""
    from app.schemas.fitness_coach import (
        ScienceRegisterInput, ScienceTopic, SourceType,
    )
    from app.services.fitness import science

    alice, _ = two_athletes
    before_docs = pg.execute(text("SELECT COUNT(*) FROM document")).scalar()
    before_chunks = pg.execute(text("SELECT COUNT(*) FROM doc_chunk")).scalar()

    asyncio.run(science.register_source(
        pg, alice,
        ScienceRegisterInput(
            title="A paper", source_type=SourceType.RCT,
            topics=[ScienceTopic.STRENGTH], doi="10.7777/paper",
        ),
        content=("Methods\nA study of squats. " * 40).encode(),
        mime_type="text/plain",
    ))

    assert pg.execute(text("SELECT COUNT(*) FROM document")).scalar() == before_docs
    assert pg.execute(
        text("SELECT COUNT(*) FROM doc_chunk")
    ).scalar() == before_chunks


def test_the_module_does_not_call_pkg_or_memory_extraction():
    """A structural check beside the behavioural one above: the import that
    would start doing it is not there."""
    from app.services.fitness import science

    source = open(science.__file__).read()
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    for forbidden in ("personal_knowledge_graph", "pkg_extractor",
                      "memory_scorer", "store_episode", "upsert_fact"):
        assert forbidden not in code, forbidden


# ─────────────────────────────────────────────────────────────────────────
# SSRF and resource bounds
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/x",
    "http://localhost/x",
    "http://10.185.1.8:8686/v1/models",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/x",
])
def test_an_internal_url_is_refused(url):
    """This container sits on a LAN with the LLM hosts, Home Assistant, the
    Proxmox API and the database. Fetching an internal URL and filing the
    response as a paper is a request forgery with a citation field."""
    from app.services.fitness import science

    with pytest.raises(science.ScienceError) as excinfo:
        science.assert_fetchable(url)
    assert excinfo.value.category.value == "fetch_blocked"


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "data:text/plain;base64,aGVsbG8=",
    "gopher://example.invalid/",
    "ftp://example.invalid/paper.pdf",
])
def test_a_non_http_scheme_is_refused(url):
    from app.services.fitness import science

    with pytest.raises(science.ScienceError) as excinfo:
        science.assert_fetchable(url)
    assert excinfo.value.category.value == "fetch_blocked"


def test_a_service_port_is_refused():
    from app.services.fitness import science

    with pytest.raises(science.ScienceError) as excinfo:
        science.assert_fetchable("http://example.com:5432/db")
    assert "service port" in str(excinfo.value)


def test_a_host_resolving_to_both_public_and_private_is_refused(monkeypatch):
    """Checking only the first resolved address is how a DNS answer with
    one public and one private record gets connected to the private one."""
    from app.services.fitness import science

    monkeypatch.setattr(
        science, "_resolve", lambda host: ["93.184.216.34", "10.0.0.5"],
    )
    with pytest.raises(science.ScienceError) as excinfo:
        science.assert_fetchable("http://mixed.example/paper")
    assert "10.0.0.5" in str(excinfo.value)


def test_a_public_host_passes(monkeypatch):
    """The guard has to let real sources through, or it is just an outage."""
    from app.services.fitness import science

    monkeypatch.setattr(science, "_resolve", lambda host: ["93.184.216.34"])
    host, port = science.assert_fetchable("https://example.com/paper.pdf")
    assert host == "example.com"
    assert port == 443


def test_an_unresolvable_host_is_refused(monkeypatch):
    from app.services.fitness import science

    monkeypatch.setattr(science, "_resolve", lambda host: [])
    with pytest.raises(science.ScienceError) as excinfo:
        science.assert_fetchable("https://nope.invalid/paper")
    assert "does not resolve" in str(excinfo.value)


def test_the_chunker_refuses_a_book():
    """A 300-page book is 700 embedding round-trips on the background
    lane."""
    from app.services.fitness import science

    with pytest.raises(science.ScienceError) as excinfo:
        science.chunk_sections("word " * 200_000)
    assert excinfo.value.category.value == "too_large"


def test_oversized_content_is_refused_before_extraction():
    from app.services.fitness import science

    with pytest.raises(science.ScienceError) as excinfo:
        science.extract_text(
            b"x" * (science.MAX_SOURCE_BYTES + 1), "text/plain", "big.txt",
        )
    assert excinfo.value.category.value == "too_large"


def test_chunks_carry_their_section_and_offsets():
    """A reader given "it says so in the paper" cannot check anything."""
    from app.services.fitness import science

    body = (
        "Abstract\nWe studied squats.\n\n"
        + "Methods\n" + ("Participants trained three times weekly. " * 40)
        + "\n\nResults\n" + ("Strength increased in both groups. " * 40)
    )
    chunks = science.chunk_sections(body)
    sections = {chunk.section for chunk in chunks}
    assert "Methods" in sections
    assert "Results" in sections
    for chunk in chunks:
        assert chunk.char_end > chunk.char_start
        # The offset has to actually locate the text in the source.
        assert body[chunk.char_start:chunk.char_end].strip().startswith(
            chunk.text[:20]
        ) or chunk.text[:20] in body[chunk.char_start:chunk.char_end]


# ─────────────────────────────────────────────────────────────────────────
# Citation validation
# ─────────────────────────────────────────────────────────────────────────

def _hit(record_id="rec-1", chunk_id="chunk-1", revision=1):
    from app.schemas.fitness_coach import ScienceSearchHit, SourceType

    return ScienceSearchHit(
        record_id=record_id, revision=revision, chunk_id=chunk_id,
        title="A paper", source_type=SourceType.RCT, text="some text",
        section="Results", char_start=0, char_end=9,
    )


@requires_pg
def test_only_offered_chunk_ids_survive_validation(pg, two_athletes):
    """§28.5. A model asked to cite its sources produces a real record id
    with the wrong chunk, or a well-formed id for a paper that suits the
    claim better than the one it was shown. Both resolve to real-looking
    text."""
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    offered = [_hit(record_id=record_id, chunk_id=chunk_id)]

    kept, rejected = science.validate_citations(
        pg, alice,
        [
            {"chunk_id": chunk_id},
            {"chunk_id": str(uuid.uuid4())},
            {"chunk_id": ""},
        ],
        offered,
    )
    assert [citation.chunk_id for citation in kept] == [chunk_id]
    assert len(rejected) == 2
    assert "not among the 1 passages supplied" in rejected[0]


@requires_pg
def test_a_citation_naming_the_wrong_record_is_rejected(pg, two_athletes):
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    kept, rejected = science.validate_citations(
        pg, alice,
        [{"chunk_id": chunk_id, "record_id": "some-other-record"}],
        [_hit(record_id=record_id, chunk_id=chunk_id)],
    )
    assert kept == []
    assert "belongs to record" in rejected[0]


@requires_pg
def test_a_citation_retracted_between_retrieval_and_storage_is_dropped(
    pg, two_athletes,
):
    """Otherwise a review ends up citing a withdrawn paper, with the
    citation trail saying it was valid."""
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    offered = [_hit(record_id=record_id, chunk_id=chunk_id)]

    pg.execute(text("""
        UPDATE fitness_science_record
        SET status = 'retracted', retracted_at = NOW() WHERE id = :id
    """), {"id": record_id})
    pg.commit()

    kept, rejected = science.validate_citations(
        pg, alice, [{"chunk_id": chunk_id}], offered,
    )
    assert kept == []
    assert "no longer retrievable" in rejected[0]


@requires_pg
def test_a_citation_records_the_exact_revision_and_location(pg, two_athletes):
    """The completion criterion: the trail reconstructs exactly what was
    retrieved."""
    from app.services.fitness import science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    kept, _ = science.validate_citations(
        pg, alice, [{"chunk_id": chunk_id}],
        [_hit(record_id=record_id, chunk_id=chunk_id, revision=1)],
    )
    citation = kept[0]
    assert citation.record_id == record_id
    assert citation.revision == 1
    assert citation.section == "Results"
    assert citation.ranking_policy_version == (
        science.SCIENCE_RANKING_POLICY_VERSION
    )


# ─────────────────────────────────────────────────────────────────────────
# Coverage: an empty library says so
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_coverage_reports_an_empty_library_honestly(pg, two_athletes):
    """§28.7. "The research suggests" over nothing is the failure this
    whole step exists to prevent."""
    from app.services.fitness import science

    alice, _ = two_athletes
    report = science.coverage(pg, alice)
    assert report["accepted_total"] == 0
    assert set(report["topics_with_no_evidence"]) == {
        "hypertrophy", "strength", "nutrition", "sleep", "recovery",
        "cardio", "injury", "supplements",
    }


@requires_pg
def test_coverage_counts_only_accepted_records(pg, two_athletes):
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status="unreviewed", topics=("sleep",),
            url="https://example.invalid/1")
    _record(pg, alice, status="accepted", topics=("sleep",),
            url="https://example.invalid/2")
    report = science.coverage(pg, alice)
    assert report["accepted_total"] == 1
    assert report["accepted_by_topic"]["sleep"] == 1
    assert report["by_status"]["unreviewed"] == 1
    assert "sleep" not in report["topics_with_no_evidence"]


@requires_pg
def test_the_library_lists_unreviewed_first(pg, two_athletes):
    """The screen is a queue, and a queue sorted by date buries the thing
    it exists for."""
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(pg, alice, status="accepted", title="Older, accepted",
            url="https://example.invalid/old")
    _record(pg, alice, status="unreviewed", title="Newer, waiting",
            url="https://example.invalid/new")
    titles = [item["title"] for item in science.library(pg, alice)]
    assert titles[0] == "Newer, waiting"

# ─────────────────────────────────────────────────────────────────────────
# The review integration: bounded evidence, validated citations
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_review_with_an_empty_library_gets_no_evidence_block(
    pg, two_athletes, stub_embeddings,
):
    """Most libraries are empty, and the prompt has to say so rather than
    letting the model fill the gap from memory."""
    from app.prompts import fitness_coach_review as prompts
    from app.services.fitness import reviews

    alice, _ = two_athletes
    evidence = asyncio.run(reviews._retrieve_evidence(pg, alice, _bare_state()))
    assert evidence == []

    rendered = prompts.build_user_prompt({}, [], has_science_corpus=False)
    assert "no curated research library is attached" in rendered
    assert "never on a named study or author" in rendered


@requires_pg
def test_a_review_retrieves_only_accepted_evidence(
    pg, two_athletes, stub_embeddings,
):
    """The isolated retrieval roundtrip the plan gates on, through the
    review's own entry point rather than the search API."""
    from app.services.fitness import reviews

    alice, _ = two_athletes
    _record(
        pg, alice, status="unreviewed", title="Unreviewed protein paper",
        topics=("nutrition",), url="https://example.invalid/unreviewed",
        text_body="Protein intake above 1.6 g/kg produced no further gains.",
    )
    _record(
        pg, alice, status="accepted", title="Accepted protein paper",
        topics=("nutrition",), url="https://example.invalid/accepted",
        text_body="Protein intake above 1.6 g/kg produced no further gains.",
        limitations="trained men only",
    )

    evidence = asyncio.run(reviews._retrieve_evidence(pg, alice, _bare_state()))
    assert [hit.title for hit in evidence] == ["Accepted protein paper"]


@requires_pg
def test_review_evidence_is_bounded(pg, two_athletes, stub_embeddings):
    """Twenty passages a reviewer cannot check is how an unverifiable
    bibliography appears under a weekly review."""
    from app.services.fitness import reviews

    alice, _ = two_athletes
    for index in range(10):
        _record(
            pg, alice, status="accepted", title=f"Paper {index}",
            topics=("nutrition", "sleep", "hypertrophy"),
            url=f"https://example.invalid/p{index}",
            text_body=(
                f"Protein, sleep and training volume findings, set {index}."
            ),
            limitations="trained men only",
        )
    evidence = asyncio.run(reviews._retrieve_evidence(pg, alice, _bare_state()))
    assert len(evidence) <= reviews.MAX_EVIDENCE_PASSAGES
    # And one passage per record, so a single paper cannot fill the budget.
    assert len({hit.record_id for hit in evidence}) == len(evidence)


@requires_pg
def test_a_retrieval_failure_does_not_fail_the_review(
    pg, two_athletes, monkeypatch,
):
    """A review without evidence is worth having. A review that did not
    happen because the GPU host was down is not."""
    from app.services.fitness import reviews, science

    alice, _ = two_athletes
    _record(pg, alice, status="accepted")

    async def explode(*args, **kwargs):
        raise RuntimeError("the embedding host is unreachable")

    monkeypatch.setattr(science, "search", explode)
    assert asyncio.run(
        reviews._retrieve_evidence(pg, alice, _bare_state())
    ) == []


@requires_pg
def test_the_prompt_lists_the_citable_ids_and_the_mismatches(
    pg, two_athletes, stub_embeddings,
):
    """§28.5: the offered set IS the citable set, so the model has to see
    each id — and the population mismatch, or it applies the finding
    anyway."""
    from app.prompts import fitness_coach_review as prompts
    from app.services.fitness import science

    alice, _ = two_athletes
    _record(
        pg, alice, status="accepted", title="Trained men, high volume",
        population="resistance-trained men", limitations="trained men only",
    )
    hits = asyncio.run(science.search(
        pg, alice, "training volume",
        athlete=science.AthleteContext(training_level="beginner"),
    ))
    rendered = prompts.build_user_prompt(
        {}, [], has_science_corpus=True,
        evidence=[hit.model_dump(mode="json") for hit in hits],
    )
    assert hits[0].chunk_id in rendered
    assert "ONLY research you may cite" in rendered
    assert "will be stripped" in rendered
    assert "MISMATCH:" in rendered
    assert "population: resistance-trained men" in rendered
    # And the no-corpus note is NOT also present, which would contradict it.
    assert "no curated research library is attached" not in rendered


def test_a_metric_path_is_not_mistaken_for_a_chunk_id():
    """`evidence_refs` carries both. Telling them apart by shape means a
    malformed ref fails one check rather than slipping through both."""
    from app.schemas.fitness_coach import (
        CoachReviewOutputV1, ConfidenceCategory, ProposedChange,
        ProposedChangeKind, RecommendationCategory, ReviewRecommendation,
    )
    from app.services.fitness.reviews import _cited_science

    chunk_id = str(uuid.uuid4())
    output = CoachReviewOutputV1(
        summary="A summary.", coaching_priority="Keep going.",
        confidence=ConfidenceCategory.LOW, confidence_basis="little data",
        recommendations=[ReviewRecommendation(
            category=RecommendationCategory.NUTRITION_CHANGE,
            headline="Hold calories where they are.",
            rationale="The rate of loss is inside the target band.",
            metric_paths=["weight.velocity_weekly"],
            # Both kinds of ref in one list, which is how they arrive.
            evidence_refs=["weight.velocity_weekly", chunk_id],
            confidence=ConfidenceCategory.LOW,
            confidence_basis="four weeks of weigh-ins",
            proposed_change=ProposedChange(kind=ProposedChangeKind.NONE),
        )],
    )
    cited = _cited_science(output)
    assert cited == [{"chunk_id": chunk_id}]


@requires_pg
def test_the_citation_trail_is_stored_on_the_review(pg, two_athletes):
    """The completion criterion: the trail reconstructs the exact retrieved
    versions."""
    from app.services.fitness import reviews, science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    review_id = _insert_review(pg, alice)

    citations, _ = science.validate_citations(
        pg, alice, [{"chunk_id": chunk_id}],
        [_hit(record_id=record_id, chunk_id=chunk_id)],
    )
    reviews._store_citations(pg, alice, review_id, citations, offered=3)
    pg.commit()

    row = pg.execute(text("""
        SELECT science_citations, science_policy_version, science_offered
        FROM fitness_coach_review WHERE id = :id
    """), {"id": review_id}).fetchone()
    stored = row.science_citations
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert stored[0]["record_id"] == record_id
    assert stored[0]["chunk_id"] == chunk_id
    assert stored[0]["revision"] == 1
    assert row.science_policy_version == (
        science.SCIENCE_RANKING_POLICY_VERSION
    )
    # Offered-but-not-cited is recorded, so "given no evidence" and
    # "retrieval never ran" stay distinguishable.
    assert row.science_offered == 3


@requires_pg
def test_a_review_given_no_evidence_records_zero_not_null(pg, two_athletes):
    from app.services.fitness import reviews

    alice, _ = two_athletes
    review_id = _insert_review(pg, alice)
    reviews._store_citations(pg, alice, review_id, [], offered=0)
    pg.commit()
    row = pg.execute(text("""
        SELECT science_citations, science_offered
        FROM fitness_coach_review WHERE id = :id
    """), {"id": review_id}).fetchone()
    assert row.science_offered == 0
    stored = row.science_citations
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert stored == []


@requires_pg
def test_a_retracted_source_names_the_reviews_that_cited_it(pg, two_athletes):
    """§28.6: flag retractions for impacted reviews. A review whose evidence
    was withdrawn needs a person, not a silent edit."""
    from app.schemas.fitness_coach import CurationAction, ScienceCurationInput
    from app.services.fitness import reviews, science

    alice, _ = two_athletes
    record_id, _, chunk_id = _record(pg, alice, status="accepted")
    review_id = _insert_review(pg, alice)

    citations, _ = science.validate_citations(
        pg, alice, [{"chunk_id": chunk_id}],
        [_hit(record_id=record_id, chunk_id=chunk_id)],
    )
    reviews._store_citations(pg, alice, review_id, citations, offered=1)
    pg.commit()

    result = science.curate(pg, alice, record_id, ScienceCurationInput(
        action=CurationAction.RETRACT, revision=1,
        reason="the journal withdrew it for data irregularities",
    ))
    assert review_id in result["affected_review_ids"]
    # The review itself is untouched: its advice may still stand, and that
    # is a judgement for David.
    status = pg.execute(text("""
        SELECT status FROM fitness_coach_review WHERE id = :id
    """), {"id": review_id}).scalar()
    assert status == "complete"


def _bare_state():
    """The smallest `FitnessStateV1` the evidence path needs.

    Retrieval is scoped by fixed queries rather than by the state's text, so
    an empty state is enough — and using one keeps this test about
    retrieval instead of about state assembly.
    """
    from datetime import date, datetime, timedelta, timezone as tz

    from app.schemas.fitness_coach import FitnessStateV1, Freshness, Period

    today = date.today()
    return FitnessStateV1(
        user_id="state-owner",
        as_of=datetime.now(tz.utc),
        athlete_local_date=today,
        timezone="America/New_York",
        period=Period(start=today - timedelta(days=28), end=today),
        freshness=Freshness.FRESH,
        data_revision="test",
    )


def _insert_review(pg, user_id):
    """A completed review row.

    Every NOT NULL column is named rather than relying on defaults: the
    citation-trail assertions are a completion criterion for this step, and
    a helper that silently returned None would turn them into skips that
    read as passes.
    """
    review_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_coach_review (
            id, user_id, kind, status, period_start, period_end,
            input_state, input_hash, state_schema_version,
            analytics_version, collected_at, prompt_version,
            requested_by, revision, attempt, output_schema_version, output,
            summary, created_at, updated_at
        ) VALUES (
            :id, :u, 'weekly', 'complete', CURRENT_DATE - 28, CURRENT_DATE,
            '{}'::jsonb, :hash, 1, 1, NOW(), 'v1', 'user', 1, 1, 1,
            CAST(:output AS JSONB), 'A summary.', NOW(), NOW()
        )
    """), {
        "id": review_id, "u": user_id,
        "hash": hashlib.sha256(review_id.encode()).hexdigest(),
        # `ck_coach_review_complete_has_output` (Step 19): a review that
        # claims to be complete and holds no output is the state nothing
        # can interpret.
        "output": json.dumps({"summary": "A summary."}),
    })
    pg.commit()
    return review_id
