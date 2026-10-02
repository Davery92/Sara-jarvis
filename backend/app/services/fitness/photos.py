"""Progress-photo ingest: bounded, sanitised, and honest about cleanup.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 26. Completion criteria: the existing
storage is extended rather than duplicated; image privacy and cleanup
failures are tracked truthfully; standardised captures work with no LLM.

These are somebody's body, so the failure modes are not abstract:

1. **No mislabelled fallback.** The old path caught every decode error and
   stored the ORIGINAL bytes with `mime_type="image/jpeg"`. That is a lie
   about the content type, and worse: the original bytes carry the EXIF GPS
   tag, so a photo taken at home shipped its coordinates into object
   storage. An undecodable upload is now REFUSED. "It still works, just
   without a thumbnail" is not worth a location leak.

2. **Bounded before decode.** A byte cap, read in chunks so an oversized
   upload never lands in memory whole; then a pixel cap, because a 20 KB PNG
   can declare 50,000 x 50,000 and Pillow will try to allocate it. Both
   checks happen before any pixels are touched.

3. **EXIF is stripped, not relied upon.** The orientation is applied and the
   image is re-encoded from pixels, so nothing from the original metadata
   survives. Asserted by a test rather than assumed from Pillow's defaults.

4. **An upload that fails to commit does not orphan bytes.** The blobs are
   deleted if the row cannot be written. If THAT delete fails, the fact is
   logged with the keys, because silence would leave private bytes nobody
   knows about.

5. **A delete whose blobs survive says so.** The row is marked
   `pending_cleanup` with the error rather than being removed — removing it
   would leave private bytes in object storage with nothing recording that
   they exist. An hourly sweep retries; a photo the athlete deleted is a
   privacy debt, not a tidy-up.

Nothing here calls a model. `bodyweight` stays a display snapshot: §26.1 is
explicit that the legacy field is never an automatic authoritative weight
ingestion, so it is neither deleted nor promoted — `bodyweight_observation_id`
is the reference a reader should trust.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

#: Hard byte cap, checked while streaming. A modern phone photo is 2-6 MB;
#: 25 lets a RAW-ish HEIC through and still refuses an upload that would be
#: a memory problem before it is an image problem.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Chunk size for the streaming read. Small enough that the cap is enforced
#: long before the whole body is resident.
READ_CHUNK = 256 * 1024

#: Pixel cap, checked from the DECLARED dimensions before decoding. A 20 KB
#: PNG can claim 50,000 x 50,000 — Pillow will then try to allocate 7.5 GB.
#: 50 megapixels is well above any phone and far below a problem.
MAX_PIXELS = 50_000_000

#: Longest edge of the stored image. A 2048 px long edge is more than any
#: comparison needs and keeps the bucket from growing by 8 MB a photo.
STORED_LONG_EDGE = 2048
THUMB_LONG_EDGE = 500

#: The only formats accepted. An upload whose real content is not one of
#: these is refused rather than stored with a guessed type.
ALLOWED_FORMATS = {"JPEG", "PNG", "HEIF", "HEIC", "WEBP", "MPO"}
ALLOWED_MIME_PREFIX = "image/"

VIEWS = ("front", "side", "back", "other")


class PhotoRejected(FitnessDataError):
    """The upload is not a usable image, or is too large. Never stored."""


@dataclass
class ProcessedImage:
    full_bytes: bytes
    thumb_bytes: bytes
    width: int
    height: int
    sha256: str
    source_format: str


# ─────────────────────────────────────────────────────────────────────────
# Reading and validating
# ─────────────────────────────────────────────────────────────────────────

async def read_bounded(upload) -> bytes:
    """Read an UploadFile with a hard cap, in chunks.

    `await file.read()` with no argument reads the whole body into memory
    first and checks the size afterwards, which is the wrong order: by then
    the damage is done. This stops at the cap.
    """
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise PhotoRejected(
                f"that image is larger than "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            )
        chunks.append(chunk)
    if total == 0:
        raise PhotoRejected("the upload was empty")
    return b"".join(chunks)


def process_image(raw: bytes, *, declared_mime: Optional[str] = None) -> ProcessedImage:
    """Validate, normalise, strip metadata, and derive a thumbnail.

    Raises `PhotoRejected` rather than falling back. The old fallback stored
    the original bytes labelled `image/jpeg`, which both lied about the type
    and preserved the EXIF GPS tag — so a photo taken at home shipped its
    coordinates into object storage.
    """
    if declared_mime and not str(declared_mime).startswith(ALLOWED_MIME_PREFIX):
        raise PhotoRejected(
            f"{declared_mime!r} is not an image content type"
        )

    try:
        from PIL import Image, ImageFile, ImageOps
    except ImportError as exc:  # pragma: no cover - Pillow is a hard dep here
        raise PhotoRejected(
            "image processing is unavailable on this server"
        ) from exc

    # Pillow's own decompression guard, set to our cap. Without it Pillow
    # warns at 89 megapixels and raises only above twice that.
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS

    try:
        probe = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as exc:
        # Pillow's own guard fires at OPEN time once MAX_IMAGE_PIXELS is
        # set, before the explicit dimension check below gets a look in.
        # Given its own message because "not an image we can read" would
        # send someone re-exporting a perfectly good file.
        raise PhotoRejected(
            f"that image declares more than "
            f"{MAX_PIXELS // 1_000_000} megapixels, which is above the limit"
        ) from exc
    except Exception as exc:
        raise PhotoRejected(
            "that file is not an image we can read"
        ) from exc

    source_format = (probe.format or "").upper()
    if source_format not in ALLOWED_FORMATS:
        raise PhotoRejected(
            f"{source_format or 'unknown'} images are not supported; send a "
            f"JPEG, PNG, HEIC or WEBP"
        )

    # The DECLARED dimensions, before any pixels are decoded. This is the
    # decompression-bomb check: a 20 KB PNG can claim 50,000 x 50,000.
    declared_pixels = (probe.width or 0) * (probe.height or 0)
    if declared_pixels <= 0:
        raise PhotoRejected("that image declares no dimensions")
    if declared_pixels > MAX_PIXELS:
        raise PhotoRejected(
            f"that image declares {declared_pixels / 1_000_000:.0f} "
            f"megapixels, above the {MAX_PIXELS // 1_000_000} megapixel limit"
        )

    try:
        image = Image.open(io.BytesIO(raw))
        # Honour the orientation tag, then discard everything else by
        # re-encoding from pixels.
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.load()
    except Image.DecompressionBombError as exc:
        raise PhotoRejected(
            f"that image expands past the "
            f"{MAX_PIXELS // 1_000_000} megapixel limit when decoded"
        ) from exc
    except Exception as exc:
        raise PhotoRejected(
            "that image could not be decoded"
        ) from exc

    width, height = image.size
    if width * height > MAX_PIXELS:
        raise PhotoRejected("that image is too large to process")

    stored = image
    long_edge = max(width, height)
    if long_edge > STORED_LONG_EDGE:
        scale = STORED_LONG_EDGE / long_edge
        stored = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )

    full_buf = io.BytesIO()
    # No `exif=` argument, so nothing from the original metadata is carried.
    # Re-encoding from pixels is what actually removes GPS; relying on
    # Pillow's default would make this a property of a library version.
    stored.save(full_buf, format="JPEG", quality=88, optimize=True)
    full_bytes = full_buf.getvalue()

    thumb = image.copy()
    thumb.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE), Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="JPEG", quality=80, optimize=True)

    if not _is_metadata_clean(full_bytes):
        # Belt and braces. If a future Pillow starts carrying EXIF through a
        # re-encode, refusing is the right failure — the alternative is
        # silently shipping coordinates.
        raise PhotoRejected(
            "the processed image still carries metadata; refusing to store it"
        )

    return ProcessedImage(
        full_bytes=full_bytes,
        thumb_bytes=thumb_buf.getvalue(),
        width=width, height=height,
        sha256=hashlib.sha256(full_bytes).hexdigest(),
        source_format=source_format,
    )


def _is_metadata_clean(jpeg_bytes: bytes) -> bool:
    """True when the encoded JPEG carries no EXIF or GPS block.

    Checked on the OUTPUT, not assumed from the encoder's defaults. The
    thing being protected is a home address.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(jpeg_bytes)) as image:
            exif = image.getexif()
            if exif and len(exif) > 0:
                return False
            if getattr(image, "info", None):
                for key in ("exif", "gps", "GPSInfo", "icc_profile"):
                    if image.info.get(key):
                        return False
    except Exception:
        # Unreadable output is its own problem, caught by the caller.
        return False
    # And the raw marker, for anything the parser does not surface.
    return b"\xff\xe1" not in jpeg_bytes[:4096]


# ─────────────────────────────────────────────────────────────────────────
# Storing
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class StoredKeys:
    storage_key: str
    thumbnail_key: Optional[str]


def store_image(processor, image: ProcessedImage) -> StoredKeys:
    """Put both objects, through the existing abstraction.

    Synchronous wrapper around the async store so the caller can keep the
    whole upload in one place. The existing `DocumentProcessor` keys and
    bucket are reused — §26.3: preserve the existing object keys.
    """
    import asyncio

    async def _store():
        full_key = await processor.store_file(
            image.full_bytes, "progress.jpg", "image/jpeg",
        )
        thumb_key = None
        try:
            thumb_key = await processor.store_file(
                image.thumb_bytes, "progress_thumb.jpg", "image/jpeg",
            )
        except Exception as exc:
            # A missing thumbnail degrades the grid; a missing full image
            # loses the photo. Only the second is fatal.
            logger.warning(
                "progress-photo thumbnail not stored (%s): %s",
                type(exc).__name__, exc,
            )
        return StoredKeys(storage_key=full_key, thumbnail_key=thumb_key)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_store())
    # Already inside a loop (the FastAPI handler). The caller awaits.
    raise RuntimeError(
        "store_image was called from a running event loop; await "
        "store_image_async instead"
    )


async def store_image_async(processor, image: ProcessedImage) -> StoredKeys:
    full_key = await processor.store_file(
        image.full_bytes, "progress.jpg", "image/jpeg",
    )
    thumb_key = None
    try:
        thumb_key = await processor.store_file(
            image.thumb_bytes, "progress_thumb.jpg", "image/jpeg",
        )
    except Exception as exc:
        logger.warning(
            "progress-photo thumbnail not stored (%s): %s",
            type(exc).__name__, exc,
        )
    return StoredKeys(storage_key=full_key, thumbnail_key=thumb_key)


def discard_stored(processor, keys: StoredKeys, *, why: str) -> None:
    """Delete blobs whose row could not be written.

    If the delete itself fails, the keys are LOGGED. Silence here would
    leave private bytes in object storage that nothing knows about — the
    log line is the only record that they need removing by hand.
    """
    for key in (keys.storage_key, keys.thumbnail_key):
        if not key:
            continue
        try:
            processor.delete_file(key)
        except Exception as exc:
            logger.error(
                "ORPHANED progress-photo object %s (%s after %s): %s — these "
                "are private bytes with no row; remove them manually",
                key, type(exc).__name__, why, exc,
            )


# ─────────────────────────────────────────────────────────────────────────
# Deleting, truthfully
# ─────────────────────────────────────────────────────────────────────────

def delete_photo(db: Session, user_id: str, photo_id: str, processor) -> Dict[str, Any]:
    """Delete the photo, and say so only if the bytes are actually gone.

    When the blob delete fails the row is marked `pending_cleanup` and kept.
    Removing it would leave private bytes in object storage with nothing
    recording that they exist — which is the worst of both outcomes: the
    athlete believes the photo is gone and it is still there.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, storage_key, thumbnail_key, cleanup_attempts
        FROM progress_photo
        WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
        FOR UPDATE
    """), {"id": photo_id, "uid": uid}).fetchone()
    if row is None:
        # 404 for a foreign or already-deleted id, never 403.
        raise LookupError("progress photo not found")

    failures: List[str] = []
    for key in (row.storage_key, row.thumbnail_key):
        if not key:
            continue
        try:
            processor.delete_file(key)
        except Exception as exc:
            failures.append(f"{key}: {type(exc).__name__}")

    if failures:
        db.execute(text("""
            UPDATE progress_photo
            SET deleted_at = NOW(), cleanup_state = 'pending_cleanup',
                cleanup_attempts = cleanup_attempts + 1,
                cleanup_error = :err, updated_at = NOW()
            WHERE id = :id AND user_id = :uid
        """), {
            "id": photo_id, "uid": uid, "err": "; ".join(failures)[:300],
        })
        return {
            "id": photo_id,
            "deleted": False,
            "cleanup_state": "pending_cleanup",
            # Said plainly. "Deleted" when the bytes are still there is the
            # one message this must not send.
            "message": (
                "Removed from your gallery, but the stored image could not be "
                "deleted yet. It is queued for retry and will not appear "
                "anywhere in the meantime."
            ),
        }

    db.execute(text("""
        UPDATE progress_photo
        SET deleted_at = NOW(), cleanup_state = 'cleaned',
            storage_key = '', thumbnail_key = NULL, updated_at = NOW()
        WHERE id = :id AND user_id = :uid
    """), {"id": photo_id, "uid": uid})
    return {
        "id": photo_id, "deleted": True, "cleanup_state": "cleaned",
        "message": "Deleted.",
    }


#: After this many failed attempts a row is marked `orphaned` rather than
#: retried forever. An unbounded retry hides the problem in a log nobody
#: reads; `orphaned` is a queryable statement that bytes need removing.
MAX_CLEANUP_ATTEMPTS = 24


def retry_pending_cleanup(db: Session, processor, *, limit: int = 50) -> Dict[str, int]:
    """Retry the blob deletes that failed. Global, like the other sweeps.

    Reads without an owner because its job is to find outstanding privacy
    debt across everybody; it never returns bytes or metadata, only counts.
    """
    rows = db.execute(text("""
        SELECT id, user_id, storage_key, thumbnail_key, cleanup_attempts
        FROM progress_photo
        WHERE cleanup_state = 'pending_cleanup'
          AND cleanup_attempts < :max
        ORDER BY cleanup_attempts ASC
        LIMIT :lim
    """), {"max": MAX_CLEANUP_ATTEMPTS, "lim": max(1, min(limit, 200))}).fetchall()

    cleaned = 0
    still_failing = 0
    for row in rows:
        failures = []
        for key in (row.storage_key, row.thumbnail_key):
            if not key:
                continue
            try:
                processor.delete_file(key)
            except Exception as exc:
                failures.append(f"{key}: {type(exc).__name__}")
        if failures:
            still_failing += 1
            db.execute(text("""
                UPDATE progress_photo
                SET cleanup_attempts = cleanup_attempts + 1,
                    cleanup_error = :err, updated_at = NOW()
                WHERE id = :id
            """), {"id": row.id, "err": "; ".join(failures)[:300]})
        else:
            cleaned += 1
            db.execute(text("""
                UPDATE progress_photo
                SET cleanup_state = 'cleaned', cleanup_error = NULL,
                    storage_key = '', thumbnail_key = NULL, updated_at = NOW()
                WHERE id = :id
            """), {"id": row.id})

    # Anything past the attempt ceiling becomes a queryable statement rather
    # than a line in a log nobody reads.
    exhausted = db.execute(text("""
        UPDATE progress_photo
        SET cleanup_state = 'orphaned', updated_at = NOW()
        WHERE cleanup_state = 'pending_cleanup' AND cleanup_attempts >= :max
        RETURNING id
    """), {"max": MAX_CLEANUP_ATTEMPTS}).fetchall()
    if exhausted:
        logger.error(
            "%d progress-photo object(s) remain in storage after %d attempts "
            "and are now marked orphaned — these are private bytes a person "
            "asked to have deleted",
            len(exhausted), MAX_CLEANUP_ATTEMPTS,
        )

    return {
        "cleaned": cleaned,
        "still_failing": still_failing,
        "orphaned": len(exhausted),
    }


# ─────────────────────────────────────────────────────────────────────────
# Capture metadata
# ─────────────────────────────────────────────────────────────────────────

def normalise_view(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    cleaned = str(value).strip().lower()
    if cleaned not in VIEWS:
        raise PhotoRejected(
            f"{value!r} is not a view ({', '.join(VIEWS)})"
        )
    return cleaned


def assert_period_owned(db: Session, user_id: str, period_id: Optional[str]) -> None:
    """A photo's capture period must be the athlete's own.

    Checked here as well as by the migration's trigger: a 422 naming the
    problem is a better answer than an integrity error, and the trigger is
    the backstop for any path that forgets.
    """
    if not period_id:
        return
    owner = db.execute(text("""
        SELECT user_id FROM fitness_measurement_period WHERE id = :id
    """), {"id": period_id}).scalar()
    if owner is None:
        raise LookupError("capture period not found")
    if owner != user_id:
        # LookupError, not a permission error: confirming the period exists
        # to someone who does not own it is itself a disclosure.
        raise LookupError("capture period not found")


def link_bodyweight_observation(
    db: Session, user_id: str, photo_id: str, *, on_date,
) -> Optional[str]:
    """Point the photo at the weight observation for its day, if there is one.

    A REFERENCE, not a copy. `health_metric` is the authority: it has a
    recorded time, a source, and the ability to be corrected. The legacy
    `bodyweight` float on this row stays as display context — §26.1 says
    that snapshot is never an automatic authoritative ingestion, so it is
    neither deleted nor promoted.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id FROM health_metric
        WHERE user_id = :uid AND metric_type IN ('weight', 'body_weight')
          AND logical_date = :day AND superseded_by_id IS NULL
        ORDER BY recorded_at DESC
        LIMIT 1
    """), {"uid": uid, "day": on_date}).fetchone()
    if row is None:
        return None
    db.execute(text("""
        UPDATE progress_photo SET bodyweight_observation_id = :obs,
            updated_at = NOW()
        WHERE id = :id AND user_id = :uid
    """), {"obs": row.id, "id": photo_id, "uid": uid})
    return row.id


def set_analysis_consent(
    db: Session, user_id: str, photo_id: str, consented: bool,
) -> Dict[str, Any]:
    """Explicit consent to run a vision model over this photo.

    Separate from having uploaded it. Step 27's analysis is gated on this
    column, and the default is false — an upload is a record the athlete
    wanted kept, not permission to have a model look at their body.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        UPDATE progress_photo
        SET consent_analysis = :consented,
            consent_analysis_at = CASE WHEN :consented THEN NOW() ELSE NULL END,
            updated_at = NOW()
        WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
        RETURNING id, consent_analysis, consent_analysis_at
    """), {"id": photo_id, "uid": uid, "consented": bool(consented)}).fetchone()
    if row is None:
        raise LookupError("progress photo not found")
    return {
        "id": row.id,
        "consent_analysis": bool(row.consent_analysis),
        "consent_analysis_at": (
            row.consent_analysis_at.isoformat()
            if row.consent_analysis_at else None
        ),
    }


def comparable(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Whether two photos can honestly be compared.

    Photo-to-photo difference is dominated by lighting, distance and pose. A
    front shot against a side shot is not a change in the athlete, and two
    shots under different lighting differ visibly with no change at all —
    so a pair that is not comparable has to be able to say which.
    """
    if a.get("view") and b.get("view") and a["view"] != b["view"]:
        return False, (
            f"one is a {a['view']} view and the other a {b['view']} view"
        )
    if not a.get("view") or not b.get("view"):
        return False, "at least one photo has no recorded view"
    if a.get("lighting") and b.get("lighting") and a["lighting"] != b["lighting"]:
        return False, (
            f"the lighting differs ({a['lighting']} vs {b['lighting']}), "
            f"which changes the image more than a week of training does"
        )
    a_distance, b_distance = a.get("distance_cm"), b.get("distance_cm")
    if a_distance and b_distance and abs(a_distance - b_distance) > 30:
        return False, (
            f"the camera distance differs by "
            f"{abs(a_distance - b_distance)} cm, which changes apparent size"
        )
    return True, None
