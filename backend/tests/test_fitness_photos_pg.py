"""Step 26 of FITNESS_COACH_IMPLEMENTATION_PLAN: progress photos are bounded,
sanitised, owner-scoped, and honest about what was actually deleted.

These are somebody's body, so the failure modes are concrete:

* The old upload path caught every decode error and stored the ORIGINAL
  bytes with `mime_type="image/jpeg"`. That lied about the type and
  preserved the EXIF GPS tag — a photo taken at home shipped its
  coordinates into object storage. An undecodable upload is now refused.
* The old delete logged a failed blob removal and deleted the row anyway,
  leaving private bytes in storage with nothing recording that they exist:
  the athlete believes the photo is gone and it is still there.
* The critique prompt asked for "an estimated body-fat range" — a number
  from one photo, landing in a text field that reads like an observation,
  which `health_metric` never sees and cannot contradict.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_photos_pg.py
"""
import io
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

UTC = timezone.utc


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
    alice = f"s26a-{uuid.uuid4().hex[:17]}"
    bob = f"s26b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s26.invalid", "p": unusable_hash})
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile
                (id, user_id, timezone, created_at, updated_at)
            VALUES (:i, :u, 'America/New_York', NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("progress_photo", "fitness_measurement_period",
                  "health_metric", "fitness_athlete_profile", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


# ─────────────────────────────────────────────────────────────────────────
# Fixtures: real images
# ─────────────────────────────────────────────────────────────────────────

#: The EXIF GPS IFD tag, as a phone writes it.
GPS_IFD = 0x8825


def _jpeg(width=800, height=1200, *, with_gps=True) -> bytes:
    """A JPEG with EXIF including a real GPS block, like a phone produces.

    Built through `Exif.get_ifd` with `IFDRational` coordinates, which is
    how Pillow actually serialises a GPS block — a plain nested dict of
    integer tuples raises in the TIFF writer.
    """
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational

    image = Image.new("RGB", (width, height), (120, 110, 100))
    exif = Image.Exif()
    exif[274] = 6                     # Orientation: rotate 90
    exif[271] = "TestPhone"           # Make
    if with_gps:
        # The whole point: a home address, in the file.
        gps = exif.get_ifd(GPS_IFD)
        gps[1] = "N"
        gps[2] = (IFDRational(40), IFDRational(44), IFDRational(54))
        gps[3] = "W"
        gps[4] = (IFDRational(74), IFDRational(0), IFDRational(21))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif, quality=92)
    return buf.getvalue()


def _png(width=10, height=10) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


class _Upload:
    """The slice of UploadFile the reader uses."""

    def __init__(self, data: bytes, *, content_type="image/jpeg",
                 filename="progress.jpg"):
        self._stream = io.BytesIO(data)
        self.content_type = content_type
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size) if size and size > 0 else \
            self._stream.read()


def _read(upload):
    import asyncio
    from app.services.fitness.photos import read_bounded
    return asyncio.run(read_bounded(upload))


# ─────────────────────────────────────────────────────────────────────────
# Bounded before decode
# ─────────────────────────────────────────────────────────────────────────

def test_an_oversized_upload_is_refused_without_being_read_whole():
    """`await file.read()` with no argument reads the body first and checks
    the size afterwards, which is the wrong order."""
    from app.services.fitness.photos import MAX_UPLOAD_BYTES, PhotoRejected

    oversized = _Upload(b"\xff\xd8" + b"\x00" * (MAX_UPLOAD_BYTES + 1024))
    with pytest.raises(PhotoRejected) as excinfo:
        _read(oversized)
    assert "larger than" in str(excinfo.value)


def test_an_empty_upload_is_refused():
    from app.services.fitness.photos import PhotoRejected

    with pytest.raises(PhotoRejected):
        _read(_Upload(b""))


def test_a_normal_photo_reads_fine():
    data = _jpeg()
    assert _read(_Upload(data)) == data


def test_a_declared_pixel_bomb_is_refused_before_decoding():
    """A 20 KB PNG can declare 50,000 x 50,000, and Pillow will then try to
    allocate 7.5 GB. The check reads the header, not the pixels."""
    from app.services.fitness.photos import MAX_PIXELS, PhotoRejected, process_image

    # Hand-build a PNG header claiming an absurd size, with no real pixels.
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 50000, 50000, 8, 2, 0, 0, 0)
    bomb = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")

    with pytest.raises(PhotoRejected) as excinfo:
        process_image(bomb, declared_mime="image/png")
    assert "megapixel" in str(excinfo.value)
    assert len(bomb) < 100, "the bomb is tiny; that is the point"


def test_the_pixel_cap_is_set_on_pillow_too():
    """Pillow warns at 89 megapixels and raises only above twice that. The
    cap has to be told to it, not just checked around it."""
    from PIL import Image
    from app.services.fitness.photos import MAX_PIXELS, process_image

    process_image(_jpeg(), declared_mime="image/jpeg")
    assert Image.MAX_IMAGE_PIXELS == MAX_PIXELS


# ─────────────────────────────────────────────────────────────────────────
# No mislabelled fallback
# ─────────────────────────────────────────────────────────────────────────

def test_a_non_image_is_refused_not_stored_as_jpeg():
    """The old path stored the original bytes with `mime_type="image/jpeg"`.
    A PDF labelled as a JPEG is a lie that every later reader believes."""
    from app.services.fitness.photos import PhotoRejected, process_image

    with pytest.raises(PhotoRejected) as excinfo:
        process_image(b"%PDF-1.7\n%garbage\n", declared_mime="application/pdf")
    assert "not an image" in str(excinfo.value)


def test_truncated_image_bytes_are_refused():
    from app.services.fitness.photos import PhotoRejected, process_image

    broken = _jpeg()[:200]
    with pytest.raises(PhotoRejected):
        process_image(broken, declared_mime="image/jpeg")


def test_an_unsupported_format_is_named_in_the_refusal():
    """So the person knows what to send instead."""
    from app.services.fitness.photos import PhotoRejected, process_image

    buf = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (10, 10)).save(buf, format="BMP")
    with pytest.raises(PhotoRejected) as excinfo:
        process_image(buf.getvalue(), declared_mime="image/bmp")
    assert "JPEG" in str(excinfo.value)


def test_a_non_image_content_type_is_refused_up_front():
    from app.services.fitness.photos import PhotoRejected, process_image

    with pytest.raises(PhotoRejected) as excinfo:
        process_image(_jpeg(), declared_mime="application/octet-stream")
    assert "not an image content type" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────
# EXIF and GPS
# ─────────────────────────────────────────────────────────────────────────

def test_the_gps_tag_does_not_survive_processing():
    """The thing being protected is a home address."""
    from PIL import Image
    from app.services.fitness.photos import process_image

    original = _jpeg(with_gps=True)
    # Confirm the fixture actually carries it, so the test cannot pass
    # against an input that never had GPS.
    with Image.open(io.BytesIO(original)) as probe:
        assert dict(probe.getexif().get_ifd(GPS_IFD)), \
            "the fixture has no GPS block"

    result = process_image(original, declared_mime="image/jpeg")
    for label, data in (("full", result.full_bytes),
                        ("thumb", result.thumb_bytes)):
        with Image.open(io.BytesIO(data)) as stored:
            assert dict(stored.getexif().get_ifd(GPS_IFD)) == {}, label
            assert len(stored.getexif()) == 0, label
    # And the raw APP1 marker is gone too, for anything the parser does not
    # surface.
    assert b"Exif\x00\x00" not in result.full_bytes[:8192]


def test_the_output_is_checked_for_metadata_rather_than_trusted():
    """Relying on Pillow's default would make this a property of a library
    version. The check is on the bytes that will be stored."""
    from app.services.fitness.photos import _is_metadata_clean, process_image

    result = process_image(_jpeg(), declared_mime="image/jpeg")
    assert _is_metadata_clean(result.full_bytes) is True
    # And a file that DOES carry EXIF fails the same check.
    assert _is_metadata_clean(_jpeg(with_gps=True)) is False


def test_orientation_is_applied_before_the_metadata_is_dropped():
    """Dropping the tag without rotating the pixels would leave every iPhone
    photo sideways."""
    from app.services.fitness.photos import process_image

    # The fixture is 800x1200 with orientation 6 (rotate 90), so the
    # upright pixels are 1200x800.
    result = process_image(_jpeg(800, 1200), declared_mime="image/jpeg")
    assert (result.width, result.height) == (1200, 800)


def test_a_large_photo_is_downscaled_and_a_thumbnail_derived():
    from PIL import Image
    from app.services.fitness.photos import STORED_LONG_EDGE, process_image

    result = process_image(_jpeg(4000, 3000, with_gps=False),
                           declared_mime="image/jpeg")
    with Image.open(io.BytesIO(result.full_bytes)) as stored:
        assert max(stored.size) == STORED_LONG_EDGE
    with Image.open(io.BytesIO(result.thumb_bytes)) as thumb:
        assert max(thumb.size) <= 500
    assert len(result.sha256) == 64


def test_a_png_is_normalised_to_jpeg():
    from PIL import Image
    from app.services.fitness.photos import process_image

    result = process_image(_png(40, 40), declared_mime="image/png")
    with Image.open(io.BytesIO(result.full_bytes)) as stored:
        assert stored.format == "JPEG"


# ─────────────────────────────────────────────────────────────────────────
# Storage failures lose no bytes and orphan none
# ─────────────────────────────────────────────────────────────────────────

class _Storage:
    """A DocumentProcessor stand-in with controllable failures."""

    def __init__(self, *, fail_store=False, fail_thumb=False, fail_delete=False):
        self.objects = {}
        self.fail_store = fail_store
        self.fail_thumb = fail_thumb
        self.fail_delete = fail_delete
        self.deletes = []

    async def store_file(self, data, filename, mime_type):
        if self.fail_store:
            raise RuntimeError("minio is down")
        if self.fail_thumb and "thumb" in filename:
            raise RuntimeError("minio refused the thumbnail")
        key = f"{uuid.uuid4()}-{filename}"
        self.objects[key] = data
        return key

    def delete_file(self, key):
        self.deletes.append(key)
        if self.fail_delete:
            raise RuntimeError("minio refused the delete")
        self.objects.pop(key, None)
        return True

    def get_file(self, key, bucket=None):
        return self.objects[key]


def test_a_thumbnail_failure_does_not_lose_the_photo():
    """A missing thumbnail degrades the grid; a missing full image loses the
    photo. Only the second is fatal."""
    import asyncio
    from app.services.fitness.photos import process_image, store_image_async

    storage = _Storage(fail_thumb=True)
    image = process_image(_jpeg(), declared_mime="image/jpeg")
    keys = asyncio.run(store_image_async(storage, image))
    assert keys.storage_key in storage.objects
    assert keys.thumbnail_key is None


def test_discarding_stored_blobs_removes_both():
    from app.services.fitness.photos import StoredKeys, discard_stored

    storage = _Storage()
    storage.objects["a"] = b"x"
    storage.objects["b"] = b"y"
    discard_stored(storage, StoredKeys("a", "b"), why="test")
    assert storage.objects == {}


def test_a_discard_that_fails_logs_the_keys(caplog):
    """Silence would leave private bytes in object storage that nothing
    knows about. The log line is the only record that they need removing."""
    import logging

    from app.services.fitness.photos import StoredKeys, discard_stored

    storage = _Storage(fail_delete=True)
    with caplog.at_level(logging.ERROR):
        discard_stored(storage, StoredKeys("abc-key", None), why="row failed")
    assert "ORPHANED" in caplog.text
    assert "abc-key" in caplog.text


# ─────────────────────────────────────────────────────────────────────────
# Deleting, truthfully
# ─────────────────────────────────────────────────────────────────────────

def _insert_photo(pg, uid, *, view="front", period_id=None, keys=("k1", "t1")):
    photo_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO progress_photo
            (id, user_id, storage_key, thumbnail_key, mime_type, view,
             period_id, created_at)
        VALUES (:id, :u, :k, :t, 'image/jpeg', :v, :p, NOW())
    """), {
        "id": photo_id, "u": uid, "k": keys[0], "t": keys[1],
        "v": view, "p": period_id,
    })
    pg.commit()
    return photo_id


@requires_pg
def test_a_successful_delete_says_deleted_and_clears_the_keys(pg, two_athletes):
    from app.services.fitness.photos import delete_photo

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    storage = _Storage()
    storage.objects["k1"] = b"bytes"
    storage.objects["t1"] = b"thumb"

    result = delete_photo(pg, alice, photo_id, storage)
    pg.commit()

    assert result["deleted"] is True
    assert result["cleanup_state"] == "cleaned"
    assert storage.objects == {}
    row = pg.execute(text("""
        SELECT deleted_at, cleanup_state, storage_key, thumbnail_key
        FROM progress_photo WHERE id = :id
    """), {"id": photo_id}).fetchone()
    assert row.deleted_at is not None
    assert row.cleanup_state == "cleaned"
    assert row.storage_key == ""
    assert row.thumbnail_key is None


@requires_pg
def test_a_failed_blob_delete_does_not_claim_the_photo_is_gone(pg, two_athletes):
    """The old path logged it and removed the row anyway: the athlete
    believes the photo is gone and it is still there."""
    from app.services.fitness.photos import delete_photo

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    storage = _Storage(fail_delete=True)
    storage.objects["k1"] = b"bytes"

    result = delete_photo(pg, alice, photo_id, storage)
    pg.commit()

    assert result["deleted"] is False
    assert result["cleanup_state"] == "pending_cleanup"
    assert "could not be deleted yet" in result["message"]
    row = pg.execute(text("""
        SELECT cleanup_state, cleanup_attempts, cleanup_error, deleted_at,
               storage_key
        FROM progress_photo WHERE id = :id
    """), {"id": photo_id}).fetchone()
    assert row.cleanup_state == "pending_cleanup"
    assert row.cleanup_attempts == 1
    assert "k1" in row.cleanup_error
    # Soft-deleted, so it disappears from the gallery — but the row stays so
    # the bytes can be retried.
    assert row.deleted_at is not None
    assert row.storage_key == "k1", "the key is kept so the retry knows what"


@requires_pg
def test_a_soft_deleted_photo_is_not_deletable_again(pg, two_athletes):
    from app.services.fitness.photos import delete_photo

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    delete_photo(pg, alice, photo_id, _Storage())
    pg.commit()
    with pytest.raises(LookupError):
        delete_photo(pg, alice, photo_id, _Storage())


@requires_pg
def test_the_retry_sweep_cleans_what_it_can(pg, two_athletes):
    from app.services.fitness.photos import delete_photo, retry_pending_cleanup

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    failing = _Storage(fail_delete=True)
    failing.objects["k1"] = b"bytes"
    delete_photo(pg, alice, photo_id, failing)
    pg.commit()

    working = _Storage()
    working.objects["k1"] = b"bytes"
    working.objects["t1"] = b"thumb"
    result = retry_pending_cleanup(pg, working)
    pg.commit()

    assert result["cleaned"] == 1
    assert working.objects == {}
    row = pg.execute(text("""
        SELECT cleanup_state, storage_key, cleanup_error
        FROM progress_photo WHERE id = :id
    """), {"id": photo_id}).fetchone()
    assert row.cleanup_state == "cleaned"
    assert row.storage_key == ""
    assert row.cleanup_error is None


@requires_pg
def test_a_retry_that_fails_again_increments_the_count(pg, two_athletes):
    from app.services.fitness.photos import delete_photo, retry_pending_cleanup

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    failing = _Storage(fail_delete=True)
    delete_photo(pg, alice, photo_id, failing)
    pg.commit()

    result = retry_pending_cleanup(pg, failing)
    pg.commit()
    assert result["still_failing"] == 1
    attempts = pg.execute(text("""
        SELECT cleanup_attempts FROM progress_photo WHERE id = :id
    """), {"id": photo_id}).scalar()
    assert attempts == 2


@requires_pg
def test_an_exhausted_retry_becomes_a_queryable_orphan(pg, two_athletes):
    """An unbounded retry hides the problem in a log nobody reads;
    `orphaned` is a statement a query can find."""
    from app.services.fitness.photos import (
        MAX_CLEANUP_ATTEMPTS, delete_photo, retry_pending_cleanup,
    )

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    failing = _Storage(fail_delete=True)
    delete_photo(pg, alice, photo_id, failing)
    pg.execute(text("""
        UPDATE progress_photo SET cleanup_attempts = :n WHERE id = :id
    """), {"n": MAX_CLEANUP_ATTEMPTS, "id": photo_id})
    pg.commit()

    result = retry_pending_cleanup(pg, failing)
    pg.commit()
    assert result["orphaned"] == 1
    state = pg.execute(text("""
        SELECT cleanup_state FROM progress_photo WHERE id = :id
    """), {"id": photo_id}).scalar()
    assert state == "orphaned"


@requires_pg
def test_the_sweep_returns_counts_and_never_bytes(pg, two_athletes):
    """It reads without an owner, so it must not be able to return anybody's
    data."""
    from app.services.fitness.photos import retry_pending_cleanup

    result = retry_pending_cleanup(pg, _Storage())
    assert set(result) == {"cleaned", "still_failing", "orphaned"}
    assert all(isinstance(v, int) for v in result.values())


# ─────────────────────────────────────────────────────────────────────────
# Ownership
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_one_athlete_cannot_delete_anothers_photo(pg, two_athletes):
    from app.services.fitness.photos import delete_photo

    alice, bob = two_athletes
    photo_id = _insert_photo(pg, alice)
    storage = _Storage()
    storage.objects["k1"] = b"bytes"

    with pytest.raises(LookupError):
        delete_photo(pg, bob, photo_id, storage)
    # And nothing was removed from storage on the way to the refusal.
    assert storage.objects["k1"] == b"bytes"
    assert storage.deletes == []


@requires_pg
def test_a_photo_cannot_join_another_athletes_capture_period(pg, two_athletes):
    """§5: an FK to a UUID alone does not enforce ownership, and this one
    would put the photo into another athlete's comparison."""
    alice, bob = two_athletes
    period_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_measurement_period
            (id, user_id, measured_on, created_at)
        VALUES (:id, :u, CURRENT_DATE, NOW())
    """), {"id": period_id, "u": alice})
    pg.commit()

    with pytest.raises((IntegrityError, DBAPIError)):
        _insert_photo(pg, bob, period_id=period_id)
    pg.rollback()


@requires_pg
def test_the_service_refuses_a_foreign_period_before_the_trigger(pg, two_athletes):
    """A 404 naming nothing is a better answer than an integrity error, and
    the trigger is the backstop for a path that forgets."""
    from app.services.fitness.photos import assert_period_owned

    alice, bob = two_athletes
    period_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO fitness_measurement_period
            (id, user_id, measured_on, created_at)
        VALUES (:id, :u, CURRENT_DATE, NOW())
    """), {"id": period_id, "u": alice})
    pg.commit()

    assert_period_owned(pg, alice, period_id)       # fine
    with pytest.raises(LookupError):
        assert_period_owned(pg, bob, period_id)
    with pytest.raises(LookupError):
        assert_period_owned(pg, alice, str(uuid.uuid4()))


@requires_pg
def test_the_photo_service_refuses_a_missing_owner(pg, two_athletes):
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.photos import delete_photo, set_analysis_consent

    for bad in ("", None, "  "):
        with pytest.raises((FitnessDataError, ValueError)):
            delete_photo(pg, bad, "whatever", _Storage())
        with pytest.raises((FitnessDataError, ValueError)):
            set_analysis_consent(pg, bad, "whatever", True)


# ─────────────────────────────────────────────────────────────────────────
# Weight is referenced, not copied
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_photo_links_the_days_weight_observation(pg, two_athletes):
    """A REFERENCE. `health_metric` has a recorded time, a source and the
    ability to be corrected; a float on the photo row has none of those."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    from app.services.fitness.photos import link_bodyweight_observation

    alice, _ = two_athletes
    taken = date(2026, 9, 28)
    result = ingest_observation(
        pg, alice, metric_type="weight", value=81.0, unit=Unit.KG,
        recorded_at=dt(2026, 9, 28, 7, 0, tzinfo=ZoneInfo("America/New_York")),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()

    photo_id = _insert_photo(pg, alice)
    linked = link_bodyweight_observation(pg, alice, photo_id, on_date=taken)
    pg.commit()

    assert linked == result.observation_id
    stored = pg.execute(text("""
        SELECT bodyweight_observation_id, bodyweight FROM progress_photo
        WHERE id = :id
    """), {"id": photo_id}).fetchone()
    assert stored.bodyweight_observation_id == result.observation_id
    # The legacy float is untouched: §26.1 — the snapshot is never an
    # automatic authoritative ingestion, so it is neither promoted nor
    # deleted.
    assert stored.bodyweight is None


@requires_pg
def test_no_weight_that_day_links_nothing_rather_than_guessing(pg, two_athletes):
    from app.services.fitness.photos import link_bodyweight_observation

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    assert link_bodyweight_observation(
        pg, alice, photo_id, on_date=date(2026, 9, 28),
    ) is None


@requires_pg
def test_a_photos_bodyweight_is_never_ingested_as_an_observation(pg, two_athletes):
    """The legacy field is display context. If it were ingested, a number
    typed beside a photo would become a body measurement with a photo's
    timestamp."""
    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO progress_photo
            (id, user_id, storage_key, mime_type, bodyweight,
             bodyweight_unit, created_at)
        VALUES (:id, :u, 'k', 'image/jpeg', 181.5, 'lbs', NOW())
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :u
    """), {"u": alice}).scalar() == 0


# ─────────────────────────────────────────────────────────────────────────
# Consent
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_analysis_consent_is_off_by_default(pg, two_athletes):
    """Uploading a photo is a record the athlete wanted kept. It is not
    permission for a model to look at their body."""
    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    row = pg.execute(text("""
        SELECT consent_analysis, consent_analysis_at FROM progress_photo
        WHERE id = :id
    """), {"id": photo_id}).fetchone()
    assert row.consent_analysis is False
    assert row.consent_analysis_at is None


@requires_pg
def test_granting_consent_records_when(pg, two_athletes):
    from app.services.fitness.photos import set_analysis_consent

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    result = set_analysis_consent(pg, alice, photo_id, True)
    pg.commit()
    assert result["consent_analysis"] is True
    assert result["consent_analysis_at"]


@requires_pg
def test_withdrawing_consent_clears_the_timestamp(pg, two_athletes):
    from app.services.fitness.photos import set_analysis_consent

    alice, _ = two_athletes
    photo_id = _insert_photo(pg, alice)
    set_analysis_consent(pg, alice, photo_id, True)
    result = set_analysis_consent(pg, alice, photo_id, False)
    pg.commit()
    assert result["consent_analysis"] is False
    assert result["consent_analysis_at"] is None


@requires_pg
def test_consent_without_a_timestamp_is_refused_by_the_database(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO progress_photo
                (id, user_id, storage_key, mime_type, consent_analysis,
                 created_at)
            VALUES (:id, :u, 'k', 'image/jpeg', TRUE, NOW())
        """), {"id": str(uuid.uuid4()), "u": alice})
        pg.commit()
    pg.rollback()


@requires_pg
def test_one_athlete_cannot_consent_for_another(pg, two_athletes):
    from app.services.fitness.photos import set_analysis_consent

    alice, bob = two_athletes
    photo_id = _insert_photo(pg, alice)
    with pytest.raises(LookupError):
        set_analysis_consent(pg, bob, photo_id, True)


# ─────────────────────────────────────────────────────────────────────────
# Comparability, with no model
# ─────────────────────────────────────────────────────────────────────────

def test_two_views_are_not_comparable():
    """A front shot against a side shot is not a change in the athlete."""
    from app.services.fitness.photos import comparable

    ok, reason = comparable({"view": "front"}, {"view": "side"})
    assert ok is False
    assert "front view" in reason and "side view" in reason


def test_a_missing_view_is_not_comparable():
    """Unknown is not "probably the same angle"."""
    from app.services.fitness.photos import comparable

    ok, reason = comparable({"view": None}, {"view": "front"})
    assert ok is False
    assert "no recorded view" in reason


def test_different_lighting_is_not_comparable():
    """Two shots under different lighting differ visibly with no change at
    all, which is the most common way a photo comparison lies."""
    from app.services.fitness.photos import comparable

    ok, reason = comparable(
        {"view": "front", "lighting": "window"},
        {"view": "front", "lighting": "overhead"},
    )
    assert ok is False
    assert "lighting differs" in reason
    assert "more than a week of training" in reason


def test_a_large_distance_difference_is_not_comparable():
    from app.services.fitness.photos import comparable

    ok, reason = comparable(
        {"view": "front", "distance_cm": 200},
        {"view": "front", "distance_cm": 300},
    )
    assert ok is False
    assert "distance differs" in reason


def test_a_matched_pair_is_comparable():
    from app.services.fitness.photos import comparable

    ok, reason = comparable(
        {"view": "front", "lighting": "window", "distance_cm": 200},
        {"view": "front", "lighting": "window", "distance_cm": 205},
    )
    assert ok is True
    assert reason is None


def test_an_unknown_view_value_is_refused():
    from app.services.fitness.photos import PhotoRejected, normalise_view

    assert normalise_view("Front") == "front"
    assert normalise_view(None) is None
    with pytest.raises(PhotoRejected):
        normalise_view("diagonal-ish")


@requires_pg
def test_the_database_refuses_an_unknown_view(pg, two_athletes):
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        _insert_photo(pg, alice, view="diagonal-ish")
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# The critique asks for no numbers
# ─────────────────────────────────────────────────────────────────────────

def test_the_critique_prompt_no_longer_asks_for_a_body_fat_estimate():
    """§26.5. A model will always give one — from a single photo, with no
    calipers and no scan — and it lands in a text field that reads like an
    observation, which `health_metric` never sees and cannot contradict."""
    from app.routes.progress_photos import CRITIQUE_PROMPT

    lowered = CRITIQUE_PROMPT.lower()
    assert "estimated body-fat" not in lowered
    assert "body fat range" not in lowered
    assert "do not estimate body fat" in lowered
    assert "do not diagnose" in lowered


def test_the_photo_tables_hold_no_body_fat_field():
    """§5.5: "no body-fat percentage field or diagnosis". A prompt asking
    for one in prose is the same claim through a gap in the schema, which is
    why both halves are checked."""
    from app.models.progress_photo import ProgressPhoto

    columns = set(ProgressPhoto.__table__.columns.keys())
    for forbidden in ("body_fat", "body_fat_percent", "bf_percent",
                      "lean_mass", "estimated_body_fat"):
        assert forbidden not in columns


# ─────────────────────────────────────────────────────────────────────────
# The iOS contract
# ─────────────────────────────────────────────────────────────────────────

def test_the_response_keeps_every_field_the_ios_app_reads():
    """An iOS build that predates Step 26 reads these keys by name. Dropping
    or renaming one breaks a build that is already on the phone, and a
    native rebuild needs a woken Mac."""
    from app.routes.progress_photos import _to_summary

    class _Row:
        id = "p1"
        original_filename = "IMG_0001.HEIC"
        mime_type = "image/jpeg"
        file_size = 123456
        width = 1200
        height = 800
        taken_at = None
        notes = "leg day"
        bodyweight = 181.5
        bodyweight_unit = "lbs"
        critique = None
        critique_model = None
        critiqued_at = None
        created_at = None

    payload = _to_summary(_Row())
    for field in ("id", "original_filename", "mime_type", "file_size",
                  "width", "height", "taken_at", "notes", "bodyweight",
                  "bodyweight_unit", "critique", "critique_model",
                  "critiqued_at", "has_critique", "created_at"):
        assert field in payload, field
    # And the new fields are present-but-null on a row that predates them,
    # rather than raising.
    for field in ("view", "period_id", "consent_analysis",
                  "bodyweight_observation_id"):
        assert field in payload, field
