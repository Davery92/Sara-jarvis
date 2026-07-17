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
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.progress_photo import ProgressPhoto

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fitness/progress-photos", tags=["Progress Photos"])


CRITIQUE_PROMPT = (
    "You are an experienced physique and bodybuilding coach reviewing a client's "
    "progress photo. Give a concise, honest, and constructive critique. Cover:\n"
    "1. Overall physique impression and an estimated body-fat range.\n"
    "2. Strongest muscle groups / standout areas.\n"
    "3. Lagging areas or imbalances to prioritize.\n"
    "4. Two or three specific, actionable next steps (training focus, nutrition, "
    "or posing).\n"
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
    }


def _process_image(image_bytes: bytes) -> tuple[bytes, Optional[bytes], Optional[int], Optional[int]]:
    """Normalize the upload to JPEG and derive a small thumbnail.

    Returns (full_jpeg_bytes, thumb_jpeg_bytes, width, height). Falls back to the
    original bytes with no thumbnail if Pillow is unavailable or decoding fails
    (e.g. an unusual HEIC without pillow-heif) — the feature still works, just
    without a downscaled grid image.
    """
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)  # honor iPhone orientation
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        width, height = img.size

        # Normalize full image to JPEG (caps very large phone photos at 2048px)
        full_img = img
        long_edge = max(width, height)
        if long_edge > 2048:
            scale = 2048 / long_edge
            full_img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
        full_buf = io.BytesIO()
        full_img.save(full_buf, format="JPEG", quality=88, optimize=True)

        # Thumbnail for the grid
        thumb = img.copy()
        thumb.thumbnail((500, 500), Image.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=80, optimize=True)

        return full_buf.getvalue(), thumb_buf.getvalue(), width, height
    except Exception as e:
        logger.warning(f"Progress photo image processing failed, storing original: {e}")
        return image_bytes, None, None, None


@router.post("")
async def upload_progress_photo(
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    bodyweight: Optional[float] = Form(None),
    bodyweight_unit: Optional[str] = Form(None),
    taken_at: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a progress photo. Stored in MinIO; a thumbnail is derived server-side."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    full_bytes, thumb_bytes, width, height = _process_image(raw)

    from app.services.docs_ingest import DocumentProcessor

    processor = DocumentProcessor()
    storage_key = await processor.store_file(full_bytes, "progress.jpg", "image/jpeg")
    thumbnail_key = None
    if thumb_bytes:
        try:
            thumbnail_key = await processor.store_file(thumb_bytes, "progress_thumb.jpg", "image/jpeg")
        except Exception as e:
            logger.warning(f"Thumbnail store failed (non-fatal): {e}")

    taken_dt = None
    if taken_at:
        try:
            taken_dt = datetime.fromisoformat(taken_at.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(f"Ignoring unparseable taken_at: {taken_at!r}")

    row = ProgressPhoto(
        user_id=current_user.id,
        storage_key=storage_key,
        thumbnail_key=thumbnail_key,
        original_filename=file.filename,
        mime_type="image/jpeg",
        file_size=len(full_bytes),
        width=width,
        height=height,
        taken_at=taken_dt,
        notes=notes,
        bodyweight=bodyweight,
        bodyweight_unit=bodyweight_unit or "lbs",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_summary(row)


@router.get("")
async def list_progress_photos(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the user's progress photos, newest first (metadata only)."""
    rows = (
        db.query(ProgressPhoto)
        .filter(ProgressPhoto.user_id == current_user.id)
        .order_by(ProgressPhoto.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_summary(r) for r in rows]


def _get_owned(photo_id: str, user_id: str, db: Session) -> ProgressPhoto:
    row = (
        db.query(ProgressPhoto)
        .filter(ProgressPhoto.id == photo_id, ProgressPhoto.user_id == user_id)
        .first()
    )
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
    """Delete a progress photo and its MinIO objects."""
    row = _get_owned(photo_id, current_user.id, db)

    try:
        from app.services.docs_ingest import DocumentProcessor

        processor = DocumentProcessor()
        processor.delete_file(row.storage_key)
        if row.thumbnail_key:
            processor.delete_file(row.thumbnail_key)
    except Exception as e:
        logger.warning(f"Failed to delete progress photo blobs from MinIO: {e}")

    db.delete(row)
    db.commit()
    return {"message": "Deleted", "id": photo_id}
