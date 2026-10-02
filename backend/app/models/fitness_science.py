"""Curated exercise-science library (FITNESS_COACH_IMPLEMENTATION_PLAN §28).

Five tables, and the split is the point:

* `fitness_science_record` — the paper, as curated. Its `status` is the
  gate: a record is invisible to retrieval until somebody accepted it.
* `fitness_science_revision` — one *version of the source text*, with its
  content hash. A citation points here, not at the record, so "which exact
  text did she read" survives the PDF being replaced by a corrected one.
* `fitness_science_chunk` — section-sized pieces with a native pgvector
  column. Separate from `doc_chunk` because that table is the personal
  document store, which the chat document tools search: putting research
  papers in it would mean a question about David's own notes retrieving a
  paper, and a paper's text reaching PKG extraction (§28.2 forbids both).
  `doc_chunk_id` links back when a record came in through the document
  pipeline, so the two are reconcilable without being the same rows.
* `fitness_science_annotation` — the curator's own margin notes. Private to
  the owner, never pooled, and excluded from any shared retrieval.
* `fitness_science_curation_event` — append-only. Every accept, reject,
  supersede and retraction with its reason and its time.

The embedding column is `Vector(settings.embedding_dim)`, the same 1024 as
`doc_chunk`. A backend returning a different width is a failure, not
something to pad: a padded vector is searchable and meaningless, so the
search keeps working and the results stop meaning anything.
"""
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.config import settings
from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class FitnessScienceRecord(Base):
    """One source, owner-scoped.

    `visibility` starts at `owner` for every record (§28.3). Publishing to
    a shared library needs an admin scope, and that is a separate decision
    from accepting a paper into your own.
    """
    __tablename__ = "fitness_science_record"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(
        String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False,
    )

    title = Column(String(500), nullable=False)
    authors = Column(String(1000))
    publication_year = Column(Integer)
    journal = Column(String(300))
    #: Lowercased, prefix-stripped. The unique index relies on that.
    doi = Column(String(200))
    url = Column(String(2000))

    source_type = Column(String(40), nullable=False)
    topics = Column(JSONB, nullable=False, server_default="[]")
    population = Column(Text)
    limitations = Column(Text)
    quality = Column(String(20))

    status = Column(String(20), nullable=False, server_default="unreviewed")
    visibility = Column(String(20), nullable=False, server_default="owner")

    #: Set on SUPERSEDE. The superseded record stays readable: an older
    #: review cited it and that citation has to resolve to something.
    superseded_by_id = Column(String)
    retracted_at = Column(DateTime(timezone=True))
    retraction_reason = Column(Text)

    #: Where this came from — an upload, a URL registration, or a refresh
    #: run. A refresh-discovered record is never accepted automatically, and
    #: a reader needs to be able to tell the difference.
    discovered_by = Column(String(40), nullable=False, server_default="manual")
    discovered_run_id = Column(String)

    notes = Column(Text)
    current_revision = Column(Integer, nullable=False, server_default="1")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<FitnessScienceRecord({self.title[:40]!r} "
            f"status={self.status})>"
        )


class FitnessScienceRevision(Base):
    """One version of a record's source text.

    Immutable once `accepted_at` is set — enforced by a trigger, because
    the citation trail is only worth anything if the cited text cannot be
    edited after the fact.
    """
    __tablename__ = "fitness_science_revision"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    record_id = Column(
        String,
        ForeignKey("fitness_science_record.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False)

    #: sha256 of the extracted text. The dedup key, and the thing that makes
    #: "the publisher silently replaced the PDF" detectable.
    content_hash = Column(String(64))
    source_url = Column(String(2000))
    storage_key = Column(String(500))
    mime_type = Column(String(120))
    byte_size = Column(Integer)
    extracted_chars = Column(Integer)

    extraction_state = Column(
        String(20), nullable=False, server_default="pending",
    )
    extraction_attempts = Column(Integer, nullable=False, server_default="0")
    failure_category = Column(String(40))
    failure_detail = Column(Text)

    #: Recorded, not assumed. A library built at 1024 and later queried by a
    #: 768-dim model returns nonsense silently, and this is what makes that
    #: visible instead.
    embedding_dim = Column(Integer)
    embedding_model = Column(String(120))
    chunk_count = Column(Integer, nullable=False, server_default="0")

    accepted_at = Column(DateTime(timezone=True))
    accepted_by = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FitnessScienceChunk(Base):
    """A section-sized piece of one revision, with its native vector."""
    __tablename__ = "fitness_science_chunk"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    revision_id = Column(
        String,
        ForeignKey("fitness_science_revision.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id = Column(String, nullable=False)
    #: Denormalised so owner scoping is one predicate on this table. A join
    #: that can be forgotten is a join that will be.
    user_id = Column(String, nullable=False)

    chunk_idx = Column(Integer, nullable=False)
    #: "Methods > Participants". Shown with every hit: a sentence from a
    #: discussion section is not the same evidence as one from results.
    section = Column(String(300))
    text = Column(Text, nullable=False)
    char_start = Column(Integer)
    char_end = Column(Integer)

    embedding = Column(Vector(settings.embedding_dim))
    #: Set when this text also lives in the personal document store, so the
    #: two can be reconciled without being one table.
    doc_chunk_id = Column(String)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FitnessScienceAnnotation(Base):
    """The curator's own note on a record. Private to the owner."""
    __tablename__ = "fitness_science_annotation"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    record_id = Column(
        String,
        ForeignKey("fitness_science_record.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String, nullable=False)
    kind = Column(String(30), nullable=False, server_default="note")
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FitnessScienceCurationEvent(Base):
    """Append-only curation history. Never updated, never deleted."""
    __tablename__ = "fitness_science_curation_event"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    record_id = Column(
        String,
        ForeignKey("fitness_science_record.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String, nullable=False)
    revision = Column(Integer)
    action = Column(String(20), nullable=False)
    #: The status before and after, so the chain reads without recomputing
    #: it from the actions.
    from_status = Column(String(20))
    to_status = Column(String(20))
    reason = Column(Text, nullable=False)
    superseded_by_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FitnessScienceRefreshRun(Base):
    """One refresh attempt.

    `last_attempt_at` and `last_success_at` are different columns on
    purpose. A job that has failed every month still has a recent attempt,
    and a single `last_run_at` would show it as healthy — the same lie as a
    green `scheduled_job` row that only proves dispatch (§3).
    """
    __tablename__ = "fitness_science_refresh_run"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now())
    succeeded = Column(Boolean, nullable=False, server_default="false")
    finished_at = Column(DateTime(timezone=True))

    queried_topics = Column(JSONB, nullable=False, server_default="[]")
    candidates_seen = Column(Integer, nullable=False, server_default="0")
    queued_unreviewed = Column(Integer, nullable=False, server_default="0")
    duplicates_skipped = Column(Integer, nullable=False, server_default="0")
    retractions_flagged = Column(JSONB, nullable=False, server_default="[]")
    affected_review_ids = Column(JSONB, nullable=False, server_default="[]")
    digest_sent = Column(Boolean, nullable=False, server_default="false")
    detail = Column(Text)
