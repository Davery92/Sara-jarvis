"""Celery tasks for the curated science library.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 28.6. On `low_priority`, because
nothing waits on this: a paper queued an hour late costs nothing, and the
`health` lane carries the morning rollups.

What these tasks cannot do, by construction:

* **Accept a record.** `trg_science_accept_needs_event` refuses an
  acceptance with no curation event behind it, and a task has no reason to
  write one. §28.6: a refresh queues and digests.
* **Apply a target change.** Nothing here touches `fitness_target_revision`.
  A paper is evidence for a conversation, not an instruction.

The retry is bounded and the extraction retry counts attempts in the row
rather than relying on Celery's own counter: a worker restart resets
Celery's, and a revision that has failed three times needs to stay failed
and visible rather than being retried forever by a fresh worker.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_TIME_LIMIT = 900
TASK_SOFT_TIME_LIMIT = 840
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 300


@celery_app.task(
    bind=True,
    name="app.tasks.fitness_science.refresh_library",
    queue="low_priority",
    time_limit=TASK_TIME_LIMIT,
    soft_time_limit=TASK_SOFT_TIME_LIMIT,
    max_retries=MAX_RETRIES,
)
def refresh_library_task(
    self, user_id: str, topics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One refresh pass for one athlete.

    `user_id` is required. There is no default owner in this subsystem, and
    a task that guessed one would file papers into somebody else's library.

    No discovery source is wired by default (§28.7: this plan is not a
    supplied scientific corpus). With none configured the run records an
    attempt, succeeds at doing nothing, and says why — which is honest, and
    is also what makes "the refresh has never found anything" visible
    rather than looking like silence.
    """
    if not user_id or not str(user_id).strip():
        raise ValueError(
            "refresh_library_task requires an explicit user_id; there is no "
            "default owner in the fitness subsystem"
        )

    from app.db.session import SessionLocal
    from app.schemas.fitness_coach import ScienceTopic
    from app.services.fitness import science

    wanted: Optional[List[ScienceTopic]] = None
    if topics:
        wanted = [ScienceTopic(topic) for topic in topics]

    db = SessionLocal()
    try:
        outcome = asyncio.run(science.refresh_library(
            db, user_id, topics=wanted, discover=_configured_discovery(),
        ))
        result = outcome.validated()
        logger.info(
            "[science] refresh %s: seen=%d queued=%d dupes=%d retracted=%d",
            result.run_id, result.candidates_seen, result.queued_unreviewed,
            result.duplicates_skipped, len(result.retractions_flagged),
        )
        return result.model_dump(mode="json")
    except Exception as exc:
        db.rollback()
        logger.warning(
            "[science] refresh failed (%s): %s", type(exc).__name__, exc,
        )
        # The run row already carries `succeeded = FALSE` with its
        # `attempted_at`, so a retry that also fails leaves a history rather
        # than one timestamp that reads as healthy.
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS)
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.tasks.fitness_science.retry_failed_extractions",
    queue="low_priority",
    time_limit=TASK_TIME_LIMIT,
    soft_time_limit=TASK_SOFT_TIME_LIMIT,
)
def retry_failed_extractions_task(self, limit: int = 5) -> Dict[str, Any]:
    """Re-attempt revisions whose extraction or embedding failed.

    Bounded by `extraction_attempts` in the row, not by Celery's retry
    counter: a worker restart resets Celery's, and a revision that has
    failed three times must stay failed and visible rather than being
    retried forever by each fresh worker.

    Only `embedding_unavailable` and transport failures are retried. A
    scanned PDF with no text layer will not grow one, and retrying
    `unsupported_type` monthly is the repetitive-nag pattern in a cron.
    """
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.fitness import science

    retryable = ("embedding_unavailable", "fetch_failed")
    db = SessionLocal()
    attempted = 0
    recovered = 0
    try:
        rows = db.execute(text("""
            SELECT v.id, v.record_id, v.user_id, v.revision, v.storage_key,
                   v.mime_type, v.source_url, v.failure_category,
                   v.extraction_attempts
            FROM fitness_science_revision v
            WHERE v.extraction_state = 'failed'
              AND v.extraction_attempts < :max_attempts
              AND v.failure_category = ANY(:retryable)
            ORDER BY v.created_at ASC
            LIMIT :limit
        """), {
            "max_attempts": science.MAX_EXTRACTION_ATTEMPTS,
            "retryable": list(retryable),
            "limit": max(1, min(limit, 25)),
        }).fetchall()

        for row in rows:
            attempted += 1
            try:
                if asyncio.run(_reembed_revision(db, row)):
                    recovered += 1
            except Exception as exc:
                db.rollback()
                db.execute(text("""
                    UPDATE fitness_science_revision
                    SET extraction_attempts = extraction_attempts + 1,
                        failure_detail = :detail
                    WHERE id = :id
                """), {"detail": str(exc)[:500], "id": row.id})
                db.commit()
                logger.info(
                    "[science] retry failed for revision %s: %s", row.id, exc,
                )
        return {"attempted": attempted, "recovered": recovered}
    finally:
        db.close()


async def _reembed_revision(db, row) -> bool:
    """Re-embed one failed revision from its stored bytes.

    Returns False rather than raising when the source bytes are gone: that
    is not a transient failure and must not consume retries. The revision
    keeps its failed state and says why.
    """
    from sqlalchemy import text

    from app.services.fitness import science

    if not row.storage_key:
        db.execute(text("""
            UPDATE fitness_science_revision
            SET extraction_attempts = extraction_attempts + 1,
                failure_detail = 'no stored bytes to re-extract from'
            WHERE id = :id
        """), {"id": row.id})
        db.commit()
        return False

    from app.services.docs_ingest import DocumentProcessor

    content = DocumentProcessor().get_file(row.storage_key)
    body = science.extract_text(content, row.mime_type or "", "")
    chunks = science.chunk_sections(body)
    vectors = await science.embed_chunks(chunks)

    db.execute(text("""
        DELETE FROM fitness_science_chunk WHERE revision_id = :id
    """), {"id": row.id})
    for chunk, vector in zip(chunks, vectors):
        db.execute(text("""
            INSERT INTO fitness_science_chunk (
                id, revision_id, record_id, user_id, chunk_idx, section,
                text, char_start, char_end, embedding, created_at
            ) VALUES (
                :id, :rev, :record, :u, :idx, :section, :text, :start, :end,
                CAST(:embedding AS vector), NOW()
            )
        """), {
            "id": __import__("uuid").uuid4().hex, "rev": row.id,
            "record": row.record_id, "u": row.user_id, "idx": chunk.idx,
            "section": chunk.section, "text": chunk.text,
            "start": chunk.char_start, "end": chunk.char_end,
            "embedding": "[" + ",".join(
                f"{value:.6f}" for value in vector
            ) + "]",
        })
    from app.core.config import settings

    db.execute(text("""
        UPDATE fitness_science_revision SET
            extraction_state = 'embedded',
            extraction_attempts = extraction_attempts + 1,
            failure_category = NULL,
            failure_detail = NULL,
            content_hash = :hash,
            extracted_chars = :chars,
            embedding_dim = :dim,
            embedding_model = :model,
            chunk_count = :count
        WHERE id = :id
    """), {
        "hash": science._content_hash(body), "chars": len(body),
        "dim": settings.embedding_dim, "model": settings.embedding_model,
        "count": len(chunks), "id": row.id,
    })
    db.commit()
    logger.info("[science] re-embedded revision %s (%d chunks)",
                row.id, len(chunks))
    return True


def _configured_discovery():
    """The discovery callable, or None.

    None by default, deliberately. §28.7: "this plan is not a supplied
    scientific corpus", and a refresh that generated plausible-looking
    papers with invented DOIs would be worse than an empty library —
    everything downstream is built to treat a record as something a human
    verified at ingestion.
    """
    return None
