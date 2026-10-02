"""Progress Photos routes — upload physique photos and get an inline VLM critique.

Storage mirrors the Content Inbox (MinIO via ``DocumentProcessor``); the critique
step reuses the existing vision helpers in ``app.routes.vision``. Every route is
scoped to the authenticated user — photos are private per user.
"""
import base64
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response
from sqlalchemy import text as _sql
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.progress_photo import ProgressPhoto

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fitness/progress-photos", tags=["Progress Photos"])


# FITNESS_COACH_IMPLEMENTATION_PLAN §26.5: the body-fat request is removed.
#
# It asked for "an estimated body-fat range", and a model will always give
# one — from a single photo, with no calipers, no scan and no scale. The
# number then lands in a text field that reads like an observation, and
# `health_metric` (the actual authority for David's numbers) never sees it
# and cannot contradict it. §5.5 is explicit that photo analysis has "no
# body-fat percentage field or diagnosis"; a prompt asking for one in prose
# is the same claim through a gap in the schema.
#
# What is left is what a photo can honestly support: what stands out, what
# is lagging, and what to do about it.
CRITIQUE_PROMPT = (
    "You are an experienced physique and bodybuilding coach reviewing a client's "
    "progress photo. Give a concise, honest, and constructive critique. Cover:\n"
    "1. Overall impression — proportions, structure, what stands out.\n"
    "2. Strongest muscle groups / standout areas.\n"
    "3. Lagging areas or imbalances to prioritize.\n"
    "4. Two or three specific, actionable next steps (training focus, nutrition, "
    "or posing).\n"
    "Do NOT estimate body fat, body weight, lean mass or any other number. A "
    "single photo cannot support one, and their actual measurements are "
    "recorded elsewhere. Do not diagnose anything.\n"
    "Be direct and motivating, not flattering. Use 120-180 words, plain text, no "
    "markdown headers. If the image is not a physique/body photo, say so briefly "
    "and do not invent a critique."
)


def _to_summary(row: ProgressPhoto) -> dict:
    """Metadata payload (no image bytes) for list/detail responses."""
    return {
        "id": row.id,
        "original_filename": row.original_filename,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "taken_at": row.taken_at.isoformat() if row.taken_at else None,
        "notes": row.notes,
        "bodyweight": row.bodyweight,
        "bodyweight_unit": row.bodyweight_unit,
        "critique": row.critique,
        "critique_model": row.critique_model,
        "critiqued_at": row.critiqued_at.isoformat() if row.critiqued_at else None,
        "has_critique": bool(row.critique),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        # Step 26 capture metadata. Every field is additive: the iOS app
        # reads the keys above by name and ignores what it does not know, so
        # adding to this payload cannot break a build that is already
        # shipped.
        "view": getattr(row, "view", None),
        "period_id": getattr(row, "period_id", None),
        "capture_protocol": getattr(row, "capture_protocol", None),
        "lighting": getattr(row, "lighting", None),
        "distance_cm": getattr(row, "distance_cm", None),
        # A reference to the canonical observation. The `bodyweight` float
        # above stays as display context — §26.1: the legacy snapshot is
        # never an automatic authoritative weight ingestion.
        "bodyweight_observation_id": getattr(
            row, "bodyweight_observation_id", None,
        ),
        "consent_analysis": bool(getattr(row, "consent_analysis", False)),
        "analysis_status": getattr(row, "analysis_status", None),
    }


# `_process_image` was here. It caught every decode error and stored the
# ORIGINAL bytes with `mime_type="image/jpeg"` — which lied about the content
# type and, worse, preserved the EXIF GPS tag, so a photo taken at home
# shipped its coordinates into object storage. Step 26 moved the real
# processing into `services/fitness/photos.py`, where an undecodable upload
# is REFUSED: "it still works, just without a thumbnail" is not worth a
# location leak.


@router.post("")
async def upload_progress_photo(
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    bodyweight: Optional[float] = Form(None),
    bodyweight_unit: Optional[str] = Form(None),
    taken_at: Optional[str] = Form(None),
    # Step 26 capture metadata. All optional, so an iOS build that predates
    # them keeps working unchanged.
    view: Optional[str] = Form(None),
    period_id: Optional[str] = Form(None),
    capture_protocol: Optional[str] = Form(None),
    lighting: Optional[str] = Form(None),
    distance_cm: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a progress photo. Bounded, sanitised, and refused if unreadable.

    Step 26 hardening, in order:

    1. the body is read in chunks with a hard byte cap, so an oversized
       upload never lands in memory whole;
    2. the declared pixel count is checked BEFORE decoding, because a 20 KB
       PNG can claim 50,000 x 50,000;
    3. the image is re-encoded from pixels, which is what actually removes
       the EXIF GPS tag, and the output is checked for metadata rather than
       trusted to be clean;
    4. an undecodable or non-image upload is REFUSED, never stored under a
       guessed content type;
    5. if the row cannot be written, the stored blobs are deleted — an
       upload that fails to commit must not leave private bytes behind.
    """
    from app.services.docs_ingest import DocumentProcessor
    from app.services.fitness import photos as photo_service

    try:
        raw = await photo_service.read_bounded(file)
        image = photo_service.process_image(
            raw, declared_mime=file.content_type,
        )
        view = photo_service.normalise_view(view)
        photo_service.assert_period_owned(db, current_user.id, period_id)
    except photo_service.PhotoRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError:
        # A foreign or missing period id. 404, never 403: confirming it
        # exists to someone who does not own it is itself a disclosure.
        raise HTTPException(status_code=404, detail="Capture period not found")

    taken_dt = None
    if taken_at:
        try:
            taken_dt = datetime.fromisoformat(taken_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"taken_at is not an ISO timestamp: {taken_at!r}",
            )

    processor = DocumentProcessor()
    keys = await photo_service.store_image_async(processor, image)

    row = ProgressPhoto(
        user_id=current_user.id,
        storage_key=keys.storage_key,
        thumbnail_key=keys.thumbnail_key,
        original_filename=file.filename,
        mime_type="image/jpeg",
        file_size=len(image.full_bytes),
        width=image.width,
        height=image.height,
        taken_at=taken_dt,
        notes=notes,
        # Display context only. `bodyweight_observation_id`, set below, is
        # the reference a reader should trust.
        bodyweight=bodyweight,
        bodyweight_unit=bodyweight_unit or "lbs",
    )
    for attribute, value in (
        ("view", view), ("period_id", period_id),
        ("capture_protocol", capture_protocol), ("lighting", lighting),
        ("distance_cm", distance_cm), ("content_sha256", image.sha256),
    ):
        if hasattr(row, attribute):
            setattr(row, attribute, value)

    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception as exc:
        # The row failed. Remove the bytes rather than orphaning them —
        # these are somebody's body, sitting in object storage with nothing
        # pointing at them and nothing recording that they exist.
        db.rollback()
        photo_service.discard_stored(processor, keys, why="row insert failed")
        logger.error(
            "progress photo row not written (%s): %s", type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not save that photo. Nothing was kept.",
        )

    # Link the day's canonical weight observation, if there is one. A
    # reference, not a copy: `health_metric` has a recorded time, a source
    # and the ability to be corrected, none of which a float on this row has.
    try:
        if taken_dt or row.created_at:
            from app.services.fitness.photos import link_bodyweight_observation
            link_bodyweight_observation(
                db, current_user.id, row.id,
                on_date=(taken_dt or row.created_at).date(),
            )
            db.commit()
            db.refresh(row)
    except Exception as exc:
        db.rollback()
        logger.debug(
            "no weight observation linked to photo %s (%s)",
            row.id, type(exc).__name__,
        )

    return _to_summary(row)


@router.get("")
async def list_progress_photos(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the user's progress photos, newest first (metadata only).

    Soft-deleted rows are excluded. A row kept because its blob delete
    failed must not keep appearing in the gallery: the athlete asked for the
    photo to be gone, and the row exists only so the bytes can be retried.
    """
    query = db.query(ProgressPhoto).filter(
        ProgressPhoto.user_id == current_user.id,
    )
    if hasattr(ProgressPhoto, "deleted_at"):
        query = query.filter(ProgressPhoto.deleted_at.is_(None))
    rows = (
        query.order_by(ProgressPhoto.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_summary(r) for r in rows]


def _get_owned(photo_id: str, user_id: str, db: Session) -> ProgressPhoto:
    """The owner check every read, critique and delete goes through.

    A soft-deleted row is treated as absent: its bytes are pending removal
    and serving them would be serving a photo the athlete deleted.
    """
    query = db.query(ProgressPhoto).filter(
        ProgressPhoto.id == photo_id, ProgressPhoto.user_id == user_id,
    )
    if hasattr(ProgressPhoto, "deleted_at"):
        query = query.filter(ProgressPhoto.deleted_at.is_(None))
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Photo not found")
    return row


@router.get("/{photo_id}/file")
async def get_progress_photo_file(
    photo_id: str,
    variant: str = Query("full", pattern="^(full|thumb)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve the image bytes from MinIO (ownership enforced)."""
    row = _get_owned(photo_id, current_user.id, db)

    key = row.thumbnail_key if (variant == "thumb" and row.thumbnail_key) else row.storage_key

    try:
        from app.services.docs_ingest import DocumentProcessor

        processor = DocumentProcessor()
        file_bytes = processor.get_file(key)
    except Exception as e:
        logger.error(f"Failed to retrieve progress photo from MinIO: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    return Response(
        content=file_bytes,
        media_type=row.mime_type or "image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/{photo_id}/critique")
async def critique_progress_photo(
    photo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run the configured vision model over the photo and store its critique."""
    row = _get_owned(photo_id, current_user.id, db)

    from app.services.docs_ingest import DocumentProcessor
    from app.routes.vision import get_user_vision_settings, call_ollama_vision

    try:
        processor = DocumentProcessor()
        image_bytes = processor.get_file(row.storage_key)
    except Exception as e:
        logger.error(f"Failed to load progress photo bytes for critique: {e}")
        raise HTTPException(status_code=500, detail="Failed to load image")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    vision = await get_user_vision_settings(current_user.id, db)
    result = await call_ollama_vision(
        image_base64=image_b64,
        prompt=CRITIQUE_PROMPT,
        model=vision["vision_model"],
        endpoint=vision["vision_endpoint"],
    )

    critique_text = (result.get("response") or "").strip()
    if not critique_text:
        raise HTTPException(status_code=502, detail="Vision model returned no critique")

    row.critique = critique_text
    row.critique_model = result.get("model")
    row.critiqued_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "critique": row.critique,
        "critique_model": row.critique_model,
        "critiqued_at": row.critiqued_at.isoformat() if row.critiqued_at else None,
    }


@router.delete("/{photo_id}")
async def delete_progress_photo(
    photo_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a progress photo, and say "deleted" only if the bytes are gone.

    The old path logged a failed blob delete and removed the row anyway,
    which left private bytes in object storage with nothing recording that
    they exist — the athlete believes the photo is gone and it is still
    there. Now the row is marked `pending_cleanup` and an hourly sweep
    retries, and the response says which happened.
    """
    from app.services.docs_ingest import DocumentProcessor
    from app.services.fitness import photos as photo_service

    try:
        result = photo_service.delete_photo(
            db, current_user.id, photo_id, DocumentProcessor(),
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Progress photo not found")
    except Exception as exc:
        db.rollback()
        logger.error(
            "progress photo delete failed for %s (%s): %s",
            photo_id, type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not delete that photo. It is unchanged.",
        )
    return result


@router.post("/{photo_id}/analysis-consent")
async def set_photo_analysis_consent(
    photo_id: str,
    consented: bool = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicit consent to run a vision model over this photo.

    Separate from having uploaded it, and default false. An upload is a
    record the athlete wanted kept; it is not permission for a model to look
    at their body. Step 27's analysis is gated on this.
    """
    from app.services.fitness import photos as photo_service

    try:
        result = photo_service.set_analysis_consent(
            db, current_user.id, photo_id, consented,
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Progress photo not found")
    return result


@router.get("/periods/{period_id}/comparable")
async def check_comparable(
    period_id: str,
    against_period_id: str = Query(...),
    view: str = Query("front"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Whether two capture sessions can honestly be compared, and why not.

    No model involved. Photo-to-photo difference is dominated by lighting,
    distance and pose: a front shot against a side shot is not a change in
    the athlete, and two shots under different lighting differ visibly with
    no change at all.
    """
    from app.services.fitness import photos as photo_service

    try:
        photo_service.assert_period_owned(db, current_user.id, period_id)
        photo_service.assert_period_owned(
            db, current_user.id, against_period_id,
        )
        normalised = photo_service.normalise_view(view)
    except LookupError:
        raise HTTPException(status_code=404, detail="Capture period not found")
    except photo_service.PhotoRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def _one(pid: str):
        row = db.execute(_sql("""
            SELECT id, view, lighting, distance_cm, capture_protocol, taken_at
            FROM progress_photo
            WHERE user_id = :uid AND period_id = :pid AND view = :view
              AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
        """), {"uid": current_user.id, "pid": pid, "view": normalised}).fetchone()
        return dict(row._mapping) if row else None

    first, second = _one(period_id), _one(against_period_id)
    if first is None or second is None:
        return {
            "comparable": False,
            "reason": f"one of the sessions has no {normalised} photo",
            "photos": [],
        }
    ok, reason = photo_service.comparable(first, second)
    return {
        "comparable": ok,
        "reason": reason,
        "photos": [first["id"], second["id"]],
    }


# ─────────────────────────────────────────────────────────────────────────
# Structured observations (Step 27)
# ─────────────────────────────────────────────────────────────────────────

@router.post("/{photo_id}/analyse")
async def analyse_photo_route(
    photo_id: str,
    compare_photo_id: Optional[str] = Query(
        None,
        description="A second photo to compare against. The earlier one is "
                    "whichever was taken first.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a structured observation over a photo the athlete consented to.

    Consent is checked before the bytes are fetched — reading somebody's
    photo out of object storage to decide whether we are allowed to read it
    is the wrong way round. The endpoint must have passed the vision probe:
    a llama.cpp server without `--mmproj` serves the same model over the
    same API and silently answers the text prompt alone, which reads as a
    model with poor eyesight.

    The output has no body-fat, weight or lean-mass field, and an estimate
    smuggled into prose is rejected.
    """
    from app.services.fitness import photo_analysis

    try:
        result = await photo_analysis.analyse_photo(
            db, current_user.id, photo_id,
            compare_photo_id=compare_photo_id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Progress photo not found")
    except photo_analysis.AnalysisRefused as exc:
        raise HTTPException(status_code=409, detail={
            "code": exc.category.value,
            "message": str(exc),
        })
    except Exception as exc:
        logger.warning(
            "photo analysis failed for %s (%s): %s",
            photo_id, type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not analyse that photo. Nothing was stored.",
        )

    return {
        "analysis_id": result.analysis_id,
        "status": result.status.value,
        "duplicate": result.duplicate,
        "model_actual": result.model_actual,
        "failure_category": (
            result.failure_category.value if result.failure_category else None
        ),
        "detail": result.detail,
        "output": (
            result.output.model_dump(mode="json") if result.output else None
        ),
    }


@router.get("/analyses")
async def list_photo_analyses(
    photo_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """This athlete's observations. Owner-scoped in the query."""
    from app.services.fitness import photo_analysis

    rows = photo_analysis.list_analyses(
        db, current_user.id, photo_id=photo_id, limit=limit,
    )
    return [
        {
            **row,
            "created_at": (
                row["created_at"].isoformat() if row.get("created_at") else None
            ),
        }
        for row in rows
    ]


@router.get("/analyses/{analysis_id}")
async def get_photo_analysis(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One observation, with which model and endpoint produced it.

    `vision_verified` is on the row: a result from an unverified endpoint is
    not evidence of anything, and a reader has to be able to see that.
    """
    from app.services.fitness import photo_analysis

    try:
        row = photo_analysis.get_analysis(db, current_user.id, analysis_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Analysis not found")
    for field in ("created_at", "evaluated_at"):
        if row.get(field):
            row[field] = row[field].isoformat()
    return row


@router.get("/vision-capability")
async def get_vision_capability(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Whether a verified vision endpoint is available at all.

    Exposed so a UI can hide the analysis affordance rather than offering a
    button that always fails — and so "Sara cannot see photos right now" is
    a visible fact rather than a mysterious error.
    """
    from app.services.fitness import photo_analysis

    capability = photo_analysis.resolve_capability(db, current_user.id)
    return {
        "available": capability.verified,
        "model": capability.model,
        "endpoint": capability.endpoint,
        "detail": capability.detail,
    }
