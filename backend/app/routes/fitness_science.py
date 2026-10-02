"""`/api/fitness/science` — the curated science library.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 28.

Routes are thin: authenticate, validate, delegate, translate. The policy
lives in `services/fitness/science.py`, and there is exactly one of it, so
the tool, the review path and this API cannot disagree about what
"accepted" means.

Two deliberate choices in the error mapping:

* A foreign or missing record is **404, never 403**. A 403 confirms the row
  exists to somebody who does not own it, and the thing being confirmed
  here is what another person reads.
* A curation transition that is not defined from the current status is
  **409 with the allowed set**, so the caller can reconcile. A bare 409
  makes a client retry blindly, which is how a reject becomes an accept.

Publishing to a shared library is NOT here. §28.3: start owner-only, and
global publication needs an admin scope — `routes/automation_admin.py` has
the `require_admin` pattern for when that arrives.

Registered OUTSIDE any try/except in `main_simple.py` (gotcha 3).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile,
)
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.fitness_coach import (
    EvidenceQuality,
    ScienceAnnotationKind,
    ScienceCurationInput,
    ScienceRegisterInput,
    ScienceStatus,
    ScienceTopic,
    SourceType,
)
from app.services.fitness import science
from app.services.fitness.data_access import FitnessDataError

logger = logging.getLogger(__name__)
router = APIRouter()

#: Bounded so one request cannot read an arbitrary file into memory before
#: the service's own cap sees it.
MAX_UPLOAD_BYTES = science.MAX_SOURCE_BYTES


async def _read_bounded(upload: UploadFile) -> bytes:
    """Read an upload in slices, stopping at the cap.

    `await upload.read()` with no argument reads whatever was sent, so the
    cap has to be enforced while reading rather than checked afterwards —
    by then the memory is already spent.
    """
    buffer = bytearray()
    while True:
        piece = await upload.read(science.READ_CHUNK_BYTES)
        if not piece:
            break
        buffer.extend(piece)
        if len(buffer) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"The file is larger than "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB. A paper is "
                    f"text; something else is being uploaded here."
                ),
            )
    return bytes(buffer)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, science.ScienceError):
        return HTTPException(status_code=422, detail={
            "code": exc.category.value, "message": str(exc),
        })
    if isinstance(exc, science.CurationConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Record not found")
    if isinstance(exc, FitnessDataError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Could not do that.")


@router.get("/records")
def list_records(
    status: Optional[ScienceStatus] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """This athlete's library, unreviewed first.

    Unreviewed first because the screen is a queue: sorting by date buries
    the records that are waiting for a decision, which is the one thing the
    page exists to surface.
    """
    try:
        return science.library(db, current_user.id, status=status, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/coverage")
def get_coverage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """How much accepted evidence exists, per topic.

    §28.7: an empty library has to say so. "The research suggests" over
    nothing is the failure this step exists to prevent, and this is what
    the UI and the review prompt both read so neither can imply coverage
    that is not there.
    """
    try:
        return science.coverage(db, current_user.id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/records/upload")
async def upload_record(
    file: UploadFile = File(...),
    title: str = Form(...),
    source_type: SourceType = Form(...),
    topics: str = Form(..., description="Comma-separated topic slugs."),
    doi: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    authors: Optional[str] = Form(None),
    publication_year: Optional[int] = Form(None),
    journal: Optional[str] = Form(None),
    population: Optional[str] = Form(None),
    limitations: Optional[str] = Form(None),
    quality: Optional[EvidenceQuality] = Form(None),
    notes: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Register a paper from a file. Arrives UNREVIEWED.

    Bibliographic fields come from the caller and are never inferred from
    the filename. §28.7: whoever ingests verifies the primary source. A
    guessed year or a guessed population is worse than a blank one, because
    a blank one is visibly blank.
    """
    content = await _read_bounded(file)
    try:
        payload = ScienceRegisterInput(
            title=title, source_type=source_type,
            topics=_parse_topics(topics), doi=doi, url=url, authors=authors,
            publication_year=publication_year, journal=journal,
            population=population, limitations=limitations, quality=quality,
            notes=notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await science.register_source(
            db, current_user.id, payload, content=content,
            mime_type=file.content_type, filename=file.filename or "",
            discovered_by="upload",
        )
    except Exception as exc:
        db.rollback()
        raise _translate(exc) from exc
    return _ingest_response(result)


@router.post("/records")
async def register_by_url(
    payload: ScienceRegisterInput = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Register a paper by URL. Fetched under the SSRF and size bounds.

    The fetch happens from inside this container, which sits on a LAN with
    the LLM hosts, Home Assistant, the Proxmox API and the database — so
    the service resolves the name, checks every resolved address, and
    re-checks each redirect hop. A registration that could reach
    `169.254.169.254` is a request forgery with a citation field.
    """
    if not payload.url:
        raise HTTPException(
            status_code=422,
            detail="A URL is required here. Use /records/upload for a file.",
        )
    try:
        result = await science.register_source(
            db, current_user.id, payload, discovered_by="url",
        )
    except Exception as exc:
        db.rollback()
        raise _translate(exc) from exc
    return _ingest_response(result)


@router.post("/records/{record_id}/curate")
def curate_record(
    record_id: str,
    payload: ScienceCurationInput = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Accept, reject, supersede, retract or reopen — with a reason.

    The reason is required by the schema and by a CHECK constraint. An
    accept with no reason is a click, and the reason is what a future
    reader needs: what this paper is good for, and what it was accepted
    despite.
    """
    try:
        return science.curate(db, current_user.id, record_id, payload)
    except Exception as exc:
        db.rollback()
        raise _translate(exc) from exc


@router.get("/records/{record_id}/history")
def record_history(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Every curation decision on this record, oldest first."""
    try:
        return science.history(db, current_user.id, record_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/records/{record_id}/annotations")
def add_annotation(
    record_id: str,
    kind: ScienceAnnotationKind = Body(...),
    body: str = Body(..., min_length=1, max_length=4000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """A private margin note.

    Never pooled and never retrieved for another athlete, even if the
    record itself is later published: the note is the curator's reading of
    it, and that is personal.
    """
    try:
        annotation_id = science.annotate(
            db, current_user.id, record_id, kind, body,
        )
    except Exception as exc:
        db.rollback()
        raise _translate(exc) from exc
    return {"id": annotation_id, "record_id": record_id}


@router.get("/search")
async def search_library(
    q: str = Query(..., min_length=3, max_length=500),
    topics: Optional[str] = Query(None),
    limit: int = Query(6, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Accepted-only retrieval.

    An unreviewed record with a perfect similarity score does not appear
    here. Similarity measures wording; endorsement is a decision somebody
    made, and conflating them is how a coach ends up citing a preprint
    nobody read.
    """
    try:
        athlete = _athlete_context(db, current_user.id)
        hits = await science.search(
            db, current_user.id, q, topics=_parse_topics(topics, allow_empty=True),
            athlete=athlete, limit=limit,
        )
    except Exception as exc:
        raise _translate(exc) from exc
    return {
        "query": q,
        "hits": [hit.model_dump(mode="json") for hit in hits],
        "ranking_policy_version": science.SCIENCE_RANKING_POLICY_VERSION,
        # So a caller can tell "nothing matched" from "there is nothing to
        # match against", which are different answers to a coach.
        "library": science.coverage(db, current_user.id),
    }


@router.get("/refresh-runs")
def list_refresh_runs(
    limit: int = Query(12, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Recent refresh attempts, successes and failures alike.

    `attempted_at` and `finished_at` are both shown. A monthly job that has
    failed every month still has a recent attempt, and one timestamp would
    show it as healthy.
    """
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT id, attempted_at, finished_at, succeeded, queried_topics,
               candidates_seen, queued_unreviewed, duplicates_skipped,
               retractions_flagged, affected_review_ids, digest_sent, detail
        FROM fitness_science_refresh_run
        WHERE user_id = :u
        ORDER BY attempted_at DESC
        LIMIT :limit
    """), {"u": current_user.id, "limit": limit}).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row._mapping)
        for field_name in ("attempted_at", "finished_at"):
            if item.get(field_name):
                item[field_name] = item[field_name].isoformat()
        out.append(item)
    return out


def _parse_topics(
    raw: Optional[str], *, allow_empty: bool = False,
) -> List[ScienceTopic]:
    if not raw or not raw.strip():
        if allow_empty:
            return []
        raise HTTPException(
            status_code=422,
            detail="At least one topic is required, so retrieval can scope.",
        )
    out: List[ScienceTopic] = []
    for piece in raw.split(","):
        slug = piece.strip().lower()
        if not slug:
            continue
        try:
            out.append(ScienceTopic(slug))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{slug!r} is not a topic. Known: "
                    f"{', '.join(topic.value for topic in ScienceTopic)}."
                ),
            ) from exc
    if not out and not allow_empty:
        raise HTTPException(status_code=422, detail="No usable topics given.")
    return out


def _athlete_context(db: Session, user_id: str) -> science.AthleteContext:
    """Training level, sex and age from the profile, for applicability.

    Read here rather than inside the ranking so the comparison has two
    explicit halves. A ranking that reaches for the profile itself can
    silently start scoring on something the caller never asked about.
    """
    from sqlalchemy import text

    row = db.execute(text("""
        SELECT training_level, calculation_sex, date_of_birth
        FROM fitness_athlete_profile WHERE user_id = :u
    """), {"u": user_id}).fetchone()
    if row is None:
        return science.AthleteContext()

    age = None
    if row.date_of_birth:
        from app.core.timezone import now as local_now
        today = local_now().date()
        born = row.date_of_birth
        age = today.year - born.year - (
            (today.month, today.day) < (born.month, born.day)
        )

    # 'unknown' and 'prefer_not_to_say' are both absences here, and they
    # must stay absences: mapping either onto a sex would make a study on
    # men score as applicable to somebody who declined to say.
    sex = row.calculation_sex
    if sex in ("unknown", "prefer_not_to_say"):
        sex = None
    level = row.training_level if row.training_level != "unknown" else None

    return science.AthleteContext(
        training_level=level, sex=sex, age=age,
    )


def _ingest_response(result: science.IngestResult) -> Dict[str, Any]:
    return {
        "record_id": result.record_id,
        "revision": result.revision,
        # Always 'unreviewed' on ingest. Stated in the response so a client
        # cannot show "added to the library" as though it were usable.
        "status": result.status.value,
        "extraction_state": result.extraction_state,
        "chunk_count": result.chunk_count,
        "duplicate_of": result.duplicate_of,
        "detail": result.detail,
    }
