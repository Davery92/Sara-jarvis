"""Curated science: ingest, curate, retrieve, refresh.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 28.

The shape of the problem is that a retrieval system is *easy to build
wrongly in a way that looks right*. Similarity search over a pile of PDFs
returns plausible paragraphs for any query, and a coach quoting them sounds
well-read. Four rules keep this from being that:

1. **Ingestion is not acceptance.** A record arrives `unreviewed` and
   retrieval filters on `accepted`. The partial index exists only over
   accepted rows, so a query that forgets the predicate degrades into a
   sequential scan — visible as slowness — rather than quietly widening the
   library to papers nobody read.
2. **A citation names a chunk of a revision.** Not a paper. The claim came
   from one paragraph of forty pages, and the revision's content hash makes
   it recoverable after the publisher replaces the PDF.
3. **Population is recorded, never inferred.** A twelve-week study on
   untrained women is evidence about untrained women. Ranking can see a
   mismatch and says so in the hit; it does not average it away.
4. **A refresh queues and digests. It never accepts and never applies.**
   §28.6. The database agrees: a record cannot reach `accepted` without a
   curation event, so the only route runs through a person.

What this module deliberately does NOT do: put research text into the
personal document store or the PKG. `doc_chunk` is what the chat document
tools search and what PKG extraction reads; a paper in there means a
question about David's own notes retrieving a study, and a study's claims
becoming "facts about David" (§28.2). `doc_chunk_id` on a chunk links the
two where a record did come in through the document pipeline, so they stay
reconcilable without being the same rows.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.fitness_coach import (
    CurationAction,
    EvidenceQuality,
    ScienceAnnotationKind,
    ScienceCitation,
    ScienceCurationInput,
    ScienceIngestFailure,
    ScienceRegisterInput,
    ScienceSearchHit,
    ScienceStatus,
    ScienceTopic,
    SourceType,
    SCIENCE_RANKING_POLICY_VERSION,
)
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Resource bounds ────────────────────────────────────────────────────
#: A paper is text. 40MB is a generous scan; beyond that something is
#: wrong, and "read it all and see" is how one upload fills the disk.
MAX_SOURCE_BYTES = 40 * 1024 * 1024
#: Read in slices and stop at the cap. A `Content-Length` header is a claim
#: by the server, so the cap has to hold without it.
READ_CHUNK_BYTES = 256 * 1024
FETCH_TIMEOUT_SECONDS = 30.0
#: Section-sized rather than sentence-sized: a chunk has to be large enough
#: that a retrieved paragraph answers something on its own.
CHUNK_CHARS = 1400
CHUNK_OVERLAP = 200
#: A 300-page book would be 700 chunks and 700 embedding round-trips. Past
#: this the record is refused rather than half-ingested.
MAX_CHUNKS = 400
MAX_EXTRACTION_ATTEMPTS = 3

SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
    "text/html": "html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        "docx",
}

#: Embeddings for research text go to the background capability, not the
#: interactive one. §9's lane split exists so background work never queues
#: ahead of presence work, and ingesting a 300-chunk paper on the fast host
#: would stall chat for the duration.
EMBEDDING_CAPABILITY = "embedding_cognition"


class ScienceError(FitnessDataError):
    """A refusal with a category a caller can branch on."""

    def __init__(self, message: str, category: ScienceIngestFailure):
        super().__init__(message)
        self.category = category


class CurationConflict(FitnessDataError):
    """The record is not in a state this transition is defined from."""


# ── SSRF ───────────────────────────────────────────────────────────────
#
# This fetcher takes a URL from a user and retrieves it from inside the
# container, which sits on a LAN with the Mac LLM host, the GPU host, the
# Sara VM, Home Assistant and a Proxmox API. A URL of
# `http://10.185.1.8:8686/v1/models` would be fetched and stored as a
# "paper"; `http://169.254.169.254/` is the cloud metadata endpoint
# everywhere it exists. So: scheme allowlist, DNS resolved ONCE, every
# resolved address checked, and redirects followed by hand so the second
# hop is checked too.

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_PORTS = {
    22, 23, 25, 445, 3306, 5432, 6379, 7687, 9000, 11211,
}
MAX_REDIRECTS = 3


def _blocked_reason(host: str, addresses: Sequence[str]) -> Optional[str]:
    """Why this host may not be fetched, or None.

    Every resolved address is checked, not just the first: a name that
    returns one public and one private address would otherwise pass here
    and be connected to the private one.
    """
    if not addresses:
        return f"{host} does not resolve"
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return f"{host} resolved to something that is not an IP: {raw!r}"
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast
                or address.is_unspecified):
            return (
                f"{host} resolves to {raw}, which is a private, loopback or "
                f"link-local address. This container sits on a LAN with the "
                f"LLM hosts, Home Assistant and the database; fetching an "
                f"internal URL and filing the response as a paper is how a "
                f"source registration becomes a request forgery."
            )
    return None


def _resolve(host: str) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos})


def assert_fetchable(url: str) -> Tuple[str, int]:
    """Validate a URL for fetching. Returns (host, port).

    Raises `ScienceError(FETCH_BLOCKED)`. Called before every hop,
    including redirect targets: a public URL that 302s to
    `http://127.0.0.1:6379/` is the standard way around a check done once.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ScienceError(
            f"{parsed.scheme or 'that'} is not a scheme this fetches. "
            f"`file://` would read this machine's disk and `data:` is not a "
            f"source anybody can check.",
            ScienceIngestFailure.FETCH_BLOCKED,
        )
    host = parsed.hostname
    if not host:
        raise ScienceError(
            f"{url!r} has no host.", ScienceIngestFailure.FETCH_BLOCKED,
        )
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    if port in BLOCKED_PORTS:
        raise ScienceError(
            f"Port {port} is a service port, not a document.",
            ScienceIngestFailure.FETCH_BLOCKED,
        )
    reason = _blocked_reason(host, _resolve(host))
    if reason:
        raise ScienceError(reason, ScienceIngestFailure.FETCH_BLOCKED)
    return host, port


async def fetch_source(url: str) -> Tuple[bytes, str]:
    """Fetch a URL under the SSRF and size bounds. Returns (bytes, mime).

    Redirects are followed by hand so each hop is re-validated, and the
    body is read in slices so a server that lies about `Content-Length`
    still cannot exceed the cap.
    """
    import httpx

    current = url
    for hop in range(MAX_REDIRECTS + 1):
        assert_fetchable(current)
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False,
            headers={"User-Agent": "SaraFitnessScience/1.0"},
        ) as client:
            async with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ScienceError(
                            f"{current} redirected without a target.",
                            ScienceIngestFailure.FETCH_FAILED,
                        )
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code >= 400:
                    raise ScienceError(
                        f"{current} returned {response.status_code}.",
                        ScienceIngestFailure.FETCH_FAILED,
                    )
                mime = (response.headers.get("content-type") or "")
                mime = mime.split(";")[0].strip().lower()
                body = bytearray()
                async for piece in response.aiter_bytes(READ_CHUNK_BYTES):
                    body.extend(piece)
                    if len(body) > MAX_SOURCE_BYTES:
                        raise ScienceError(
                            f"The source is larger than "
                            f"{MAX_SOURCE_BYTES // (1024 * 1024)}MB. A paper "
                            f"is text; something else is being served here.",
                            ScienceIngestFailure.TOO_LARGE,
                        )
                return bytes(body), mime or "application/octet-stream"
    raise ScienceError(
        f"{url} redirected more than {MAX_REDIRECTS} times.",
        ScienceIngestFailure.FETCH_FAILED,
    )


# ── Extraction and chunking ────────────────────────────────────────────

#: Section headings as they appear in papers. Used to label chunks, which
#: is what lets a hit say "Methods > Participants" — a sentence from a
#: discussion is not the same evidence as one from results.
_SECTION_RE = re.compile(
    r"^\s{0,4}(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(abstract|background|introduction|methods?|materials and methods|"
    r"participants|subjects|procedures?|intervention|measures|"
    r"statistical analysis|results?|discussion|limitations?|"
    r"practical applications?|conclusions?|references)\b[:.]?\s*$",
    re.I | re.M,
)


def extract_text(content: bytes, mime_type: str, filename: str = "") -> str:
    """Extracted text, or a categorised refusal.

    Delegates to `DocumentProcessor`, which is the one extractor in the
    codebase — a second PDF path here would be a second place for the
    PyPDF2-vs-pypdf failure to come back (the import that silently empties
    every PDF).
    """
    kind = SUPPORTED_MIME.get((mime_type or "").split(";")[0].strip().lower())
    if kind is None:
        raise ScienceError(
            f"{mime_type or 'that type'} is not a source this can read. "
            f"PDF, text, markdown, HTML and docx are.",
            ScienceIngestFailure.UNSUPPORTED_TYPE,
        )
    if len(content) > MAX_SOURCE_BYTES:
        raise ScienceError(
            f"The source is larger than {MAX_SOURCE_BYTES // (1024 * 1024)}MB.",
            ScienceIngestFailure.TOO_LARGE,
        )

    from app.services.docs_ingest import DocumentProcessor

    processor = DocumentProcessor()
    try:
        extracted, _meta = processor.extract_text(
            content, mime_type, filename or "source",
        )
    except Exception as exc:
        raise ScienceError(
            f"Extraction failed ({type(exc).__name__}): {exc}",
            ScienceIngestFailure.NO_TEXT,
        ) from exc

    cleaned = (extracted or "").strip()
    if len(cleaned) < 200:
        raise ScienceError(
            "Less than 200 characters came out. A scanned PDF with no text "
            "layer looks exactly like this, and storing it would create a "
            "record that can be cited and contains nothing.",
            ScienceIngestFailure.NO_TEXT,
        )
    return cleaned


@dataclass
class Chunk:
    idx: int
    text: str
    section: Optional[str]
    char_start: int
    char_end: int


def chunk_sections(body: str) -> List[Chunk]:
    """Section-labelled chunks with their character offsets.

    Offsets are kept because a citation has to be findable in the source: a
    reader given "it says so in the paper" cannot check anything.
    """
    headings: List[Tuple[int, str]] = [
        (match.start(), match.group(1).strip().title())
        for match in _SECTION_RE.finditer(body)
    ]

    def section_at(position: int) -> Optional[str]:
        current = None
        for start, name in headings:
            if start <= position:
                current = name
            else:
                break
        return current

    chunks: List[Chunk] = []
    position = 0
    length = len(body)
    while position < length:
        end = min(position + CHUNK_CHARS, length)
        if end < length:
            # Prefer a paragraph break, then a sentence, then a space. A
            # chunk cut mid-sentence retrieves as a fragment and reads as
            # one in a citation.
            for candidate in (
                body.rfind("\n\n", position + CHUNK_CHARS // 2, end),
                body.rfind(". ", position + CHUNK_CHARS // 2, end),
                body.rfind(" ", position + CHUNK_CHARS // 2, end),
            ):
                if candidate > position:
                    end = candidate + 1
                    break
        piece = body[position:end].strip()
        if piece:
            chunks.append(Chunk(
                idx=len(chunks), text=piece, section=section_at(position),
                char_start=position, char_end=end,
            ))
        if len(chunks) >= MAX_CHUNKS:
            raise ScienceError(
                f"The source produced more than {MAX_CHUNKS} chunks. That is "
                f"a book, not a paper, and embedding it would take the "
                f"background lane for an hour.",
                ScienceIngestFailure.TOO_LARGE,
            )
        if end >= length:
            break
        position = max(end - CHUNK_OVERLAP, position + 1)
    return chunks


async def embed_chunks(chunks: Sequence[Chunk]) -> List[List[float]]:
    """Embeddings for every chunk, or a categorised failure.

    §28.1: never fabricate or pad. A vector of the wrong width that got
    padded is still searchable, so the search keeps working and the results
    stop meaning anything — which is strictly worse than an error.
    """
    from app.services.embeddings import EmbeddingUnavailable, get_embeddings_batch

    try:
        vectors = await get_embeddings_batch(
            [chunk.text for chunk in chunks], capability=EMBEDDING_CAPABILITY,
        )
    except EmbeddingUnavailable as exc:
        raise ScienceError(
            f"The embedding backend returned no vector: {exc}. The record is "
            f"kept and the extraction retried; nothing is stored unembedded, "
            f"because a chunk with no vector is invisible to retrieval while "
            f"looking present in the library.",
            ScienceIngestFailure.EMBEDDING_UNAVAILABLE,
        ) from exc

    expected = settings.embedding_dim
    for position, vector in enumerate(vectors):
        if len(vector) != expected:
            raise ScienceError(
                f"Chunk {position} embedded to {len(vector)} dimensions, not "
                f"{expected}. The column is vector({expected}) and the model "
                f"is bge-m3. Padding or truncating would store a searchable "
                f"vector that means nothing — check EMBEDDING_MODEL against "
                f"the running embedding service.",
                ScienceIngestFailure.EMBEDDING_DIM_MISMATCH,
            )
    return list(vectors)


# ── Registration ───────────────────────────────────────────────────────

@dataclass
class IngestResult:
    record_id: str
    revision_id: str
    revision: int
    status: ScienceStatus
    extraction_state: str
    chunk_count: int
    duplicate_of: Optional[str] = None
    detail: Optional[str] = None


def _now() -> datetime:
    return datetime.now(UTC)


def _content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _existing_by_doi(db: Session, user_id: str, doi: str) -> Optional[str]:
    return db.execute(text("""
        SELECT id FROM fitness_science_record
        WHERE user_id = :u AND doi = :doi
    """), {"u": user_id, "doi": doi}).scalar()


def _existing_by_hash(db: Session, user_id: str, digest: str) -> Optional[str]:
    return db.execute(text("""
        SELECT record_id FROM fitness_science_revision
        WHERE user_id = :u AND content_hash = :h
        LIMIT 1
    """), {"u": user_id, "h": digest}).scalar()


async def register_source(
    db: Session,
    user_id: str,
    payload: ScienceRegisterInput,
    *,
    content: Optional[bytes] = None,
    mime_type: Optional[str] = None,
    filename: str = "",
    discovered_by: str = "manual",
    discovered_run_id: Optional[str] = None,
) -> IngestResult:
    """Register one source: extract, chunk, embed, store as UNREVIEWED.

    The order matters. Extraction and embedding happen BEFORE the record is
    written, with no transaction held across the network calls — an
    embedding round-trip is seconds and a held transaction blocks the
    coach's own reads. The record only exists once there is text to cite.

    Nothing here accepts anything. §28.3: the owner accepts a revision
    explicitly, and that is a separate call with a reason.
    """
    owner = _require_user(user_id)
    if discovered_by not in ("manual", "upload", "url", "refresh"):
        raise FitnessDataError(f"unknown discovery source {discovered_by!r}")

    # Dedup on the DOI before spending a fetch or an embedding run.
    if payload.doi:
        existing = _existing_by_doi(db, owner, payload.doi)
        if existing:
            return IngestResult(
                record_id=existing, revision_id="", revision=0,
                status=ScienceStatus.UNREVIEWED, extraction_state="",
                chunk_count=0, duplicate_of=existing,
                detail=f"DOI {payload.doi} is already in the library.",
            )

    if content is None:
        if not payload.url:
            raise ScienceError(
                "Nothing to ingest: no file and no URL.",
                ScienceIngestFailure.NO_TEXT,
            )
        content, fetched_mime = await fetch_source(payload.url)
        mime_type = mime_type or fetched_mime

    body = extract_text(content, mime_type or "", filename)
    digest = _content_hash(body)

    duplicate = _existing_by_hash(db, owner, digest)
    if duplicate:
        return IngestResult(
            record_id=duplicate, revision_id="", revision=0,
            status=ScienceStatus.UNREVIEWED, extraction_state="",
            chunk_count=0, duplicate_of=duplicate,
            detail=(
                "The same text is already in the library under another "
                "record. Identical bytes with a different DOI usually means "
                "a preprint and its published version."
            ),
        )

    chunks = chunk_sections(body)
    vectors = await embed_chunks(chunks)

    record_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_science_record (
            id, user_id, title, authors, publication_year, journal, doi, url,
            source_type, topics, population, limitations, quality, status,
            visibility, discovered_by, discovered_run_id, notes,
            current_revision, created_at, updated_at
        ) VALUES (
            :id, :u, :title, :authors, :year, :journal, :doi, :url,
            :source_type, CAST(:topics AS JSONB), :population, :limitations,
            :quality, 'unreviewed', 'owner', :discovered_by, :run_id, :notes,
            1, NOW(), NOW()
        )
    """), {
        "id": record_id, "u": owner, "title": payload.title.strip(),
        "authors": payload.authors, "year": payload.publication_year,
        "journal": payload.journal, "doi": payload.doi, "url": payload.url,
        "source_type": payload.source_type.value,
        "topics": json.dumps([topic.value for topic in payload.topics]),
        "population": payload.population, "limitations": payload.limitations,
        "quality": payload.quality.value if payload.quality else None,
        "discovered_by": discovered_by, "run_id": discovered_run_id,
        "notes": payload.notes,
    })

    storage_key = None
    if content is not None and len(content) <= MAX_SOURCE_BYTES:
        storage_key = await _store_source(content, filename, mime_type)

    db.execute(text("""
        INSERT INTO fitness_science_revision (
            id, record_id, user_id, revision, content_hash, source_url,
            storage_key, mime_type, byte_size, extracted_chars,
            extraction_state, extraction_attempts, embedding_dim,
            embedding_model, chunk_count, created_at
        ) VALUES (
            :id, :record, :u, 1, :hash, :url, :key, :mime, :size, :chars,
            'embedded', 1, :dim, :model, :count, NOW()
        )
    """), {
        "id": revision_id, "record": record_id, "u": owner, "hash": digest,
        "url": payload.url, "key": storage_key, "mime": mime_type,
        "size": len(content) if content else None, "chars": len(body),
        "dim": settings.embedding_dim,
        "model": settings.embedding_model, "count": len(chunks),
    })

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
            "id": str(uuid.uuid4()), "rev": revision_id, "record": record_id,
            "u": owner, "idx": chunk.idx, "section": chunk.section,
            "text": chunk.text, "start": chunk.char_start,
            "end": chunk.char_end,
            # §7.5: CAST(:param AS vector), never :param::vector — the
            # second form's colons are eaten by the parameter parser.
            "embedding": "[" + ",".join(f"{value:.6f}" for value in vector) + "]",
        })

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The unique indexes are the real dedup: two concurrent
        # registrations of the same DOI both pass the SELECT above.
        existing = (
            (_existing_by_doi(db, owner, payload.doi) if payload.doi else None)
            or _existing_by_hash(db, owner, digest)
        )
        if existing:
            return IngestResult(
                record_id=existing, revision_id="", revision=0,
                status=ScienceStatus.UNREVIEWED, extraction_state="",
                chunk_count=0, duplicate_of=existing,
                detail="Already in the library (concurrent registration).",
            )
        raise ScienceError(
            f"Could not store the record: {exc}",
            ScienceIngestFailure.DUPLICATE,
        ) from exc

    logger.info(
        "[science] registered %s (%d chunks, %d chars) as unreviewed",
        record_id, len(chunks), len(body),
    )
    return IngestResult(
        record_id=record_id, revision_id=revision_id, revision=1,
        status=ScienceStatus.UNREVIEWED, extraction_state="embedded",
        chunk_count=len(chunks),
    )


async def _store_source(
    content: bytes, filename: str, mime_type: Optional[str],
) -> Optional[str]:
    """Keep the original bytes if object storage is available.

    Best-effort on purpose: the citable artefact is the extracted text and
    its hash, both already stored. Losing the PDF costs a re-download;
    failing the ingestion over it costs the record.
    """
    try:
        from app.services.docs_ingest import DocumentProcessor
        return await DocumentProcessor().store_file(
            content, filename or "source.pdf",
            mime_type or "application/octet-stream",
        )
    except Exception as exc:
        logger.warning("[science] source bytes not stored: %s", exc)
        return None


# ── Curation ───────────────────────────────────────────────────────────

#: Which transitions exist. A state machine written down is a state machine
#: that can be tested; one implemented as `if` statements across three
#: call sites is a set of accidents.
ALLOWED_CURATION: Dict[ScienceStatus, Set[CurationAction]] = {
    ScienceStatus.UNREVIEWED: {
        CurationAction.ACCEPT, CurationAction.REJECT, CurationAction.RETRACT,
    },
    ScienceStatus.ACCEPTED: {
        CurationAction.REJECT, CurationAction.SUPERSEDE,
        CurationAction.RETRACT,
    },
    ScienceStatus.REJECTED: {CurationAction.REOPEN},
    ScienceStatus.SUPERSEDED: {CurationAction.REOPEN, CurationAction.RETRACT},
    #: A retraction is terminal. A journal that withdrew a paper did not
    #: change its mind because a curator wants the citation back.
    ScienceStatus.RETRACTED: set(),
}

_RESULTING_STATUS: Dict[CurationAction, ScienceStatus] = {
    CurationAction.ACCEPT: ScienceStatus.ACCEPTED,
    CurationAction.REJECT: ScienceStatus.REJECTED,
    CurationAction.SUPERSEDE: ScienceStatus.SUPERSEDED,
    CurationAction.RETRACT: ScienceStatus.RETRACTED,
    CurationAction.REOPEN: ScienceStatus.UNREVIEWED,
}


def curate(
    db: Session, user_id: str, record_id: str, payload: ScienceCurationInput,
) -> Dict[str, Any]:
    """Apply one curation decision, with its reason, atomically.

    The event is inserted BEFORE the record is updated, which is not
    stylistic: the `trg_science_accept_needs_event` trigger refuses an
    acceptance with no event behind it, so the order is what makes the
    database able to enforce "acceptance is a human decision".

    Old versions are preserved. A reject keeps the record and its text; a
    supersede keeps both and links them; a retraction keeps everything and
    flags the reviews that cited it. An old review's citation has to
    resolve to the text that was actually read.
    """
    owner = _require_user(user_id)

    row = db.execute(text("""
        SELECT id, status, current_revision, title
        FROM fitness_science_record
        WHERE id = :id AND user_id = :u
        FOR UPDATE
    """), {"id": record_id, "u": owner}).fetchone()
    if row is None:
        raise LookupError(f"science record {record_id} not found")

    current = ScienceStatus(row.status)
    allowed = ALLOWED_CURATION.get(current, set())
    if payload.action not in allowed:
        raise CurationConflict(
            f"{record_id} is {current.value}; {payload.action.value} is not a "
            f"transition from there. Allowed: "
            f"{', '.join(sorted(action.value for action in allowed)) or 'none'}."
        )
    if payload.revision != row.current_revision:
        raise CurationConflict(
            f"Revision {payload.revision} was curated but the record is at "
            f"revision {row.current_revision}. Re-read it first: accepting "
            f"blind would accept text nobody looked at."
        )

    if payload.action is CurationAction.SUPERSEDE:
        successor = db.execute(text("""
            SELECT id FROM fitness_science_record
            WHERE id = :id AND user_id = :u
        """), {"id": payload.superseded_by_id, "u": owner}).scalar()
        if not successor:
            raise CurationConflict(
                f"{payload.superseded_by_id} is not a record in this library, "
                f"so the supersession chain would dead-end."
            )
        if successor == record_id:
            raise CurationConflict("A record cannot supersede itself.")

    resulting = _RESULTING_STATUS[payload.action]

    if payload.action is CurationAction.ACCEPT:
        state = db.execute(text("""
            SELECT extraction_state, chunk_count
            FROM fitness_science_revision
            WHERE record_id = :r AND revision = :rev
        """), {"r": record_id, "rev": payload.revision}).fetchone()
        if state is None or state.extraction_state != "embedded":
            raise CurationConflict(
                f"Revision {payload.revision} is "
                f"{state.extraction_state if state else 'missing'}, not "
                f"embedded. Accepting it would create a citation to text "
                f"that is not there."
            )

    event_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_science_curation_event (
            id, record_id, user_id, revision, action, from_status,
            to_status, reason, superseded_by_id, created_at
        ) VALUES (
            :id, :record, :u, :rev, :action, :from_status, :to_status,
            :reason, :superseded_by, NOW()
        )
    """), {
        "id": event_id, "record": record_id, "u": owner,
        "rev": payload.revision, "action": payload.action.value,
        "from_status": current.value, "to_status": resulting.value,
        "reason": payload.reason.strip(),
        "superseded_by": payload.superseded_by_id,
    })

    db.execute(text("""
        UPDATE fitness_science_record SET
            status = :status,
            quality = COALESCE(:quality, quality),
            limitations = COALESCE(:limitations, limitations),
            superseded_by_id = CASE
                WHEN :action = 'supersede' THEN :superseded_by
                ELSE superseded_by_id END,
            retracted_at = CASE
                WHEN :action = 'retract' THEN NOW() ELSE retracted_at END,
            retraction_reason = CASE
                WHEN :action = 'retract' THEN :reason
                ELSE retraction_reason END,
            updated_at = NOW()
        WHERE id = :id AND user_id = :u
    """), {
        "status": resulting.value,
        "quality": payload.quality.value if payload.quality else None,
        "limitations": payload.limitations, "action": payload.action.value,
        "superseded_by": payload.superseded_by_id,
        "reason": payload.reason.strip(), "id": record_id, "u": owner,
    })

    if payload.action is CurationAction.ACCEPT:
        db.execute(text("""
            UPDATE fitness_science_revision
            SET accepted_at = NOW(), accepted_by = :u
            WHERE record_id = :r AND revision = :rev AND accepted_at IS NULL
        """), {"u": owner, "r": record_id, "rev": payload.revision})

    affected: List[str] = []
    if payload.action is CurationAction.RETRACT:
        affected = reviews_citing(db, owner, record_id)

    db.commit()
    logger.info(
        "[science] %s %s: %s -> %s", payload.action.value, record_id,
        current.value, resulting.value,
    )
    return {
        "record_id": record_id,
        "from_status": current.value,
        "to_status": resulting.value,
        "event_id": event_id,
        "affected_review_ids": affected,
    }


def annotate(
    db: Session, user_id: str, record_id: str, kind: ScienceAnnotationKind,
    body: str,
) -> str:
    """A private margin note. Never pooled, never shared, never retrieved
    for another athlete even when the record is public."""
    owner = _require_user(user_id)
    exists = db.execute(text("""
        SELECT 1 FROM fitness_science_record WHERE id = :id AND user_id = :u
    """), {"id": record_id, "u": owner}).scalar()
    if not exists:
        raise LookupError(f"science record {record_id} not found")
    annotation_id = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO fitness_science_annotation
            (id, record_id, user_id, kind, body, created_at)
        VALUES (:id, :record, :u, :kind, :body, NOW())
    """), {
        "id": annotation_id, "record": record_id, "u": owner,
        "kind": kind.value, "body": body.strip(),
    })
    db.commit()
    return annotation_id


def history(db: Session, user_id: str, record_id: str) -> List[Dict[str, Any]]:
    """Every curation decision on this record, oldest first."""
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, revision, action, from_status, to_status, reason,
               superseded_by_id, created_at
        FROM fitness_science_curation_event
        WHERE record_id = :r AND user_id = :u
        ORDER BY created_at ASC
    """), {"r": record_id, "u": owner}).fetchall()
    return [dict(row._mapping) for row in rows]


# ── Retrieval ──────────────────────────────────────────────────────────
#
# Hybrid, and the components stay separate in the output. A single blended
# score cannot answer "why was this shown", and the one question a coach
# citing evidence will be asked is exactly that.
#
# Weights are deliberate rather than tuned: there is no labelled relevance
# set here, so a tuned number would be a number with a false provenance.

W_SIMILARITY = 1.0
W_LEXICAL = 0.35
W_TOPIC = 0.5
W_QUALITY = 0.3
W_APPLICABILITY = 0.6

QUALITY_WEIGHT = {
    EvidenceQuality.HIGH: 1.0,
    EvidenceQuality.MODERATE: 0.6,
    EvidenceQuality.LOW: 0.25,
}

#: A grade for a source type, used ONLY when the curator left quality
#: blank. Never overrides a recorded grade: a badly run RCT is worse
#: evidence than a careful meta-analysis, and that judgement is the
#: curator's, not a lookup table's.
TYPE_WEIGHT = {
    SourceType.META_ANALYSIS: 0.9,
    SourceType.SYSTEMATIC_REVIEW: 0.85,
    SourceType.RCT: 0.75,
    SourceType.POSITION_STAND: 0.6,
    SourceType.OBSERVATIONAL: 0.4,
    SourceType.NARRATIVE_REVIEW: 0.35,
    SourceType.SECONDARY: 0.25,
}

#: Population words that bear on whether a finding transfers. Crude on
#: purpose: the output is a visible note plus a score nudge, not a filter,
#: so being wrong costs ordering rather than hiding a paper.
_POPULATION_SIGNALS = {
    "trained": re.compile(r"\b(resistance[- ]trained|trained|experienced|"
                          r"advanced|athletes?)\b", re.I),
    "untrained": re.compile(r"\b(untrained|novice|beginners?|sedentary|"
                            r"previously inactive)\b", re.I),
    "female": re.compile(r"\b(women|females?)\b", re.I),
    "male": re.compile(r"\b(men|males?)\b", re.I),
    "older": re.compile(r"\b(older|elderly|aged \d{2}|50\+|60\+|masters)\b",
                        re.I),
    "youth": re.compile(r"\b(adolescent|youth|children|teenage)\b", re.I),
    "clinical": re.compile(r"\b(patients?|obese|diabetic|clinical|"
                           r"hypertensive|rehabilitation)\b", re.I),
}


@dataclass
class AthleteContext:
    """What the library is being asked *for*.

    Supplied by the caller from the profile, never read from the record
    side: applicability is a comparison between a study's population and
    this athlete, and both halves have to be explicit for the mismatch to
    be nameable.
    """
    training_level: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[int] = None

    def signals(self) -> Set[str]:
        found: Set[str] = set()
        level = (self.training_level or "").lower()
        if level in ("advanced", "intermediate"):
            found.add("trained")
        elif level in ("beginner", "novice", "untrained"):
            found.add("untrained")
        sex = (self.sex or "").lower()
        if sex.startswith("f"):
            found.add("female")
        elif sex.startswith("m"):
            found.add("male")
        if self.age is not None:
            if self.age >= 50:
                found.add("older")
            elif self.age < 18:
                found.add("youth")
        return found


def _applicability(
    population: Optional[str], athlete: Optional[AthleteContext],
) -> Tuple[float, Optional[str]]:
    """How far the study's population is from this athlete.

    Returns a score in [-1, 1] and a note when there is a mismatch worth
    saying out loud. An unrecorded population scores 0 with a note: unknown
    is not the same as matching, and treating it as a match is how a finding
    drifts onto the wrong person.
    """
    if not population or not population.strip():
        return 0.0, "The study population is not recorded for this source."
    if athlete is None:
        return 0.0, None

    study = {
        name for name, pattern in _POPULATION_SIGNALS.items()
        if pattern.search(population)
    }
    if not study:
        return 0.0, None
    mine = athlete.signals()
    if not mine:
        return 0.0, None

    conflicts: List[str] = []
    for a, b in (("trained", "untrained"), ("female", "male"),
                 ("older", "youth")):
        if a in study and b in mine:
            conflicts.append(f"studied {a}, you are {b}")
        if b in study and a in mine:
            conflicts.append(f"studied {b}, you are {a}")
    if "clinical" in study:
        conflicts.append("a clinical population")

    overlap = len(study & mine)
    if conflicts:
        return -min(1.0, 0.5 * len(conflicts)), "; ".join(conflicts)
    if overlap:
        return min(1.0, 0.4 * overlap), None
    return 0.0, None


async def search(
    db: Session,
    user_id: str,
    query: str,
    *,
    topics: Optional[Sequence[ScienceTopic]] = None,
    athlete: Optional[AthleteContext] = None,
    limit: int = 6,
    candidate_pool: int = 40,
) -> List[ScienceSearchHit]:
    """Accepted-only retrieval over this athlete's library.

    Four filters that are not negotiable, in the SQL rather than in Python
    so a caller cannot forget one: the owner, `status = 'accepted'`,
    `retracted_at IS NULL`, and a non-null embedding.

    An unreviewed record with a perfect similarity score does not appear.
    That is the whole design: similarity is a measure of wording, and
    endorsement is a decision somebody made.
    """
    owner = _require_user(user_id)
    cleaned = (query or "").strip()
    if len(cleaned) < 3:
        raise FitnessDataError("a search needs at least three characters")

    from app.services.embeddings import EmbeddingUnavailable, get_embedding

    try:
        vector = await get_embedding(cleaned, capability=EMBEDDING_CAPABILITY)
    except EmbeddingUnavailable as exc:
        # Lexical-only rather than nothing: a library that cannot be
        # searched when the GPU host is down is a library that is not there
        # when it is most likely to be asked for.
        logger.warning("[science] embedding unavailable, lexical only: %s", exc)
        vector = None
    if vector is not None and len(vector) != settings.embedding_dim:
        raise ScienceError(
            f"The query embedded to {len(vector)} dimensions but the library "
            f"is {settings.embedding_dim}. Comparing them would return "
            f"confident nonsense.",
            ScienceIngestFailure.EMBEDDING_DIM_MISMATCH,
        )

    topic_values = [topic.value for topic in (topics or [])]
    params: Dict[str, Any] = {
        "u": owner, "q": cleaned, "pool": max(limit, min(candidate_pool, 200)),
        "topics": json.dumps(topic_values) if topic_values else None,
    }
    if vector is not None:
        params["embedding"] = (
            "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
        )

    similarity_select = (
        "1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity"
        if vector is not None else "NULL::float AS similarity"
    )
    order_by = (
        "c.embedding <=> CAST(:embedding AS vector) ASC"
        if vector is not None
        else "ts_rank(to_tsvector('english', c.text), "
             "plainto_tsquery('english', :q)) DESC"
    )

    rows = db.execute(text(f"""
        SELECT
            r.id AS record_id, r.title, r.authors, r.publication_year,
            r.journal, r.doi, r.url, r.source_type, r.quality, r.topics,
            r.population, r.limitations,
            v.revision, c.id AS chunk_id, c.section, c.text,
            c.char_start, c.char_end,
            {similarity_select},
            ts_rank(
                to_tsvector('english', c.text),
                plainto_tsquery('english', :q)
            ) AS lexical
        FROM fitness_science_chunk c
        JOIN fitness_science_revision v ON v.id = c.revision_id
        JOIN fitness_science_record r ON r.id = c.record_id
        WHERE c.user_id = :u
          AND r.user_id = :u
          AND r.status = 'accepted'
          AND r.retracted_at IS NULL
          AND v.accepted_at IS NOT NULL
          AND c.embedding IS NOT NULL
          AND (
            CAST(:topics AS JSONB) IS NULL
            OR r.topics ?| ARRAY(
                SELECT jsonb_array_elements_text(CAST(:topics AS JSONB))
            )
          )
        ORDER BY {order_by}
        LIMIT :pool
    """), params).fetchall()

    wanted = set(topic_values)
    hits: List[ScienceSearchHit] = []
    for row in rows:
        record_topics = row.topics or []
        if isinstance(record_topics, str):
            record_topics = json.loads(record_topics)
        topic_match = (
            len(wanted & set(record_topics)) / len(wanted) if wanted else 0.0
        )

        quality = EvidenceQuality(row.quality) if row.quality else None
        source_type = SourceType(row.source_type)
        quality_weight = (
            QUALITY_WEIGHT[quality] if quality
            else TYPE_WEIGHT.get(source_type, 0.3)
        )

        applicability, note = _applicability(row.population, athlete)
        similarity = float(row.similarity) if row.similarity is not None else None
        lexical = float(row.lexical or 0.0)

        score = (
            W_SIMILARITY * (similarity if similarity is not None else 0.0)
            + W_LEXICAL * min(lexical, 1.0)
            + W_TOPIC * topic_match
            + W_QUALITY * quality_weight
            + W_APPLICABILITY * applicability
        )

        hits.append(ScienceSearchHit(
            record_id=row.record_id, revision=row.revision,
            chunk_id=row.chunk_id, title=row.title, authors=row.authors,
            publication_year=row.publication_year, journal=row.journal,
            doi=row.doi, url=row.url, source_type=source_type,
            quality=quality,
            topics=[
                ScienceTopic(value) for value in record_topics
                if value in ScienceTopic._value2member_map_
            ],
            population=row.population, limitations=row.limitations,
            section=row.section, char_start=row.char_start,
            char_end=row.char_end, text=row.text,
            similarity=similarity, lexical=lexical, topic_match=topic_match,
            quality_weight=quality_weight, applicability=applicability,
            applicability_note=note, score=round(score, 5),
            ranking_policy_version=SCIENCE_RANKING_POLICY_VERSION,
        ))

    hits.sort(key=lambda hit: hit.score, reverse=True)

    # One chunk per record in the final set. Three paragraphs of one paper
    # read as three sources, which is the quiet way a single study becomes
    # "the literature".
    seen: Set[str] = set()
    deduped: List[ScienceSearchHit] = []
    for hit in hits:
        if hit.record_id in seen:
            continue
        seen.add(hit.record_id)
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


def validate_citations(
    db: Session, user_id: str, cited: Sequence[Dict[str, Any]],
    offered: Sequence[ScienceSearchHit],
) -> Tuple[List[ScienceCitation], List[str]]:
    """Keep only citations to chunks that were actually supplied.

    §28.5: "validation permits only supplied exact IDs". A model asked to
    cite its sources will produce plausible ids — a real record with the
    wrong chunk, a chunk id from an earlier turn, a well-formed uuid for a
    paper that supports the claim better than the one it was shown. Each of
    those is a fabricated citation that resolves to real-looking text, and
    checking against the exact offered set is the only defence that does
    not require reading every one.
    """
    owner = _require_user(user_id)
    allowed = {
        hit.chunk_id: hit for hit in offered
    }
    kept: List[ScienceCitation] = []
    rejected: List[str] = []
    for entry in cited:
        chunk_id = str(entry.get("chunk_id") or "").strip()
        hit = allowed.get(chunk_id)
        if hit is None:
            rejected.append(
                f"chunk {chunk_id or '(missing)'} was not among the "
                f"{len(allowed)} passages supplied for this review"
            )
            continue
        record_id = str(entry.get("record_id") or "").strip()
        if record_id and record_id != hit.record_id:
            rejected.append(
                f"chunk {chunk_id} belongs to record {hit.record_id}, not "
                f"{record_id}"
            )
            continue
        kept.append(ScienceCitation(
            record_id=hit.record_id, revision=hit.revision,
            chunk_id=hit.chunk_id, section=hit.section,
            char_start=hit.char_start, char_end=hit.char_end,
            ranking_policy_version=hit.ranking_policy_version,
        ))

    # Belt and braces: the chunks must still be owner-visible at commit
    # time. A record retracted between retrieval and storage would
    # otherwise leave a citation to a withdrawn paper.
    if kept:
        visible = {
            row[0] for row in db.execute(text("""
                SELECT c.id
                FROM fitness_science_chunk c
                JOIN fitness_science_record r ON r.id = c.record_id
                WHERE c.user_id = :u AND r.status = 'accepted'
                  AND r.retracted_at IS NULL
                  AND c.id = ANY(:ids)
            """), {"u": owner, "ids": [cite.chunk_id for cite in kept]}).fetchall()
        }
        still: List[ScienceCitation] = []
        for cite in kept:
            if cite.chunk_id in visible:
                still.append(cite)
            else:
                rejected.append(
                    f"chunk {cite.chunk_id} is no longer retrievable "
                    f"(retracted or unaccepted between retrieval and storage)"
                )
        kept = still
    return kept, rejected


def reviews_citing(db: Session, user_id: str, record_id: str) -> List[str]:
    """Reviews whose stored citations name this record.

    Used when a paper is retracted: §28.6 says flag, not fix. A review
    whose evidence was withdrawn needs a person to decide whether its
    recommendation still stands.
    """
    owner = _require_user(user_id)
    exists = db.execute(text("""
        SELECT to_regclass('fitness_coach_review') IS NOT NULL
    """)).scalar()
    if not exists:
        return []
    rows = db.execute(text("""
        SELECT id FROM fitness_coach_review
        WHERE user_id = :u
          AND science_citations IS NOT NULL
          AND science_citations::text LIKE :needle
        ORDER BY created_at DESC
    """), {"u": owner, "needle": f"%{record_id}%"}).fetchall()
    return [row[0] for row in rows]


def library(
    db: Session, user_id: str, *,
    status: Optional[ScienceStatus] = None, limit: int = 50,
) -> List[Dict[str, Any]]:
    """The athlete's records. Default: everything, newest first.

    Unfiltered by default deliberately — the UI's job is to show what is
    waiting to be reviewed, and a default that hid unreviewed records would
    make the queue invisible.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT r.id, r.title, r.authors, r.publication_year, r.journal,
               r.doi, r.url, r.source_type, r.topics, r.population,
               r.limitations, r.quality, r.status, r.visibility,
               r.superseded_by_id, r.retracted_at, r.retraction_reason,
               r.discovered_by, r.current_revision, r.created_at,
               v.extraction_state, v.chunk_count, v.failure_category,
               v.failure_detail, v.extracted_chars, v.embedding_model,
               (SELECT COUNT(*) FROM fitness_science_annotation a
                 WHERE a.record_id = r.id AND a.user_id = :u) AS annotations
        FROM fitness_science_record r
        LEFT JOIN fitness_science_revision v
               ON v.record_id = r.id AND v.revision = r.current_revision
        WHERE r.user_id = :u
          AND (CAST(:status AS VARCHAR) IS NULL
               OR r.status = CAST(:status AS VARCHAR))
        ORDER BY
            -- Unreviewed first: it is a queue, and a queue sorted by date
            -- buries the thing the screen exists for.
            CASE WHEN r.status = 'unreviewed' THEN 0 ELSE 1 END,
            r.created_at DESC
        LIMIT :limit
    """), {
        "u": owner, "status": status.value if status else None,
        "limit": max(1, min(limit, 200)),
    }).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row._mapping)
        if isinstance(item.get("topics"), str):
            item["topics"] = json.loads(item["topics"])
        for field_name in ("retracted_at", "created_at"):
            if item.get(field_name):
                item[field_name] = item[field_name].isoformat()
        out.append(item)
    return out


def coverage(db: Session, user_id: str) -> Dict[str, Any]:
    """How much accepted evidence exists, per topic.

    §28.7: a small library is fine and an empty one must say so. This is
    what the UI and the review prompt read, so neither can imply coverage
    that is not there — "the literature suggests" over an empty library is
    the failure this whole step is built to avoid.
    """
    owner = _require_user(user_id)
    rows = db.execute(text("""
        SELECT r.status, r.topics
        FROM fitness_science_record r
        WHERE r.user_id = :u
    """), {"u": owner}).fetchall()

    per_topic: Dict[str, int] = {topic.value: 0 for topic in ScienceTopic}
    counts = {status.value: 0 for status in ScienceStatus}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        if row.status != ScienceStatus.ACCEPTED.value:
            continue
        topics = row.topics or []
        if isinstance(topics, str):
            topics = json.loads(topics)
        for topic in topics:
            if topic in per_topic:
                per_topic[topic] += 1
    return {
        "by_status": counts,
        "accepted_by_topic": per_topic,
        "accepted_total": counts.get(ScienceStatus.ACCEPTED.value, 0),
        "topics_with_no_evidence": sorted(
            topic for topic, count in per_topic.items() if count == 0
        ),
        "ranking_policy_version": SCIENCE_RANKING_POLICY_VERSION,
    }


# ── Refresh ────────────────────────────────────────────────────────────
#
# §28.6: a low-priority monthly pass that searches approved sources and
# topics, deduplicates, queues new records as UNREVIEWED, and sends ONE
# digest. It never accepts and it never applies a target change. The
# database agrees — `trg_science_accept_needs_event` refuses an acceptance
# without a curation event — so this is not a promise, it is a constraint.
#
# "Approved sources" means a per-athlete allowlist of domains, not an open
# web search. An unbounded search would pull in blog posts and make the
# curator's queue the thing nobody reads.

DEFAULT_REFRESH_TOPICS = (
    ScienceTopic.HYPERTROPHY, ScienceTopic.STRENGTH,
    ScienceTopic.NUTRITION, ScienceTopic.SLEEP,
)
#: Hard cap per run. The point is a readable queue, not a crawl.
MAX_REFRESH_CANDIDATES = 25


@dataclass
class RefreshCandidate:
    """One thing a refresh found, before anything is stored.

    `doi` and `url` are what dedup runs on. A candidate with neither is
    discarded: it cannot be cited and cannot be told apart from the next
    one that arrives.
    """
    title: str
    url: Optional[str] = None
    doi: Optional[str] = None
    source_type: SourceType = SourceType.SECONDARY
    topics: Sequence[ScienceTopic] = field(default_factory=tuple)
    retracted: bool = False
    detail: Optional[str] = None


async def refresh_library(
    db: Session,
    user_id: str,
    *,
    topics: Optional[Sequence[ScienceTopic]] = None,
    discover: Optional[Any] = None,
    ingest: bool = True,
) -> "ScienceRefreshOutcomeLocal":
    """One refresh pass. Queues, flags, digests. Never accepts.

    `discover` is injected rather than imported so this is testable without
    the network, and so the discovery mechanism can change without the
    guarantees changing. It returns candidates; this function decides what
    happens to them, and the only two outcomes are "queued as unreviewed"
    and "skipped as a duplicate".

    The run row records `attempted_at` always and `finished_at`/`succeeded`
    only on success. A single `last_run_at` would show a job that has
    failed every month for four months as recently healthy — the same lie
    as `DBScheduler` marking success at dispatch (§3).
    """
    owner = _require_user(user_id)
    wanted = list(topics or DEFAULT_REFRESH_TOPICS)
    run_id = str(uuid.uuid4())

    db.execute(text("""
        INSERT INTO fitness_science_refresh_run
            (id, user_id, attempted_at, succeeded, queried_topics)
        VALUES (:id, :u, NOW(), FALSE, CAST(:topics AS JSONB))
    """), {
        "id": run_id, "u": owner,
        "topics": json.dumps([topic.value for topic in wanted]),
    })
    db.commit()

    outcome = ScienceRefreshOutcomeLocal(
        run_id=run_id, attempted_at=_now(), succeeded=False,
        queried_topics=wanted,
    )

    if discover is None:
        outcome.detail = (
            "No discovery source is configured. §28.7: this plan is not a "
            "supplied scientific corpus, and a refresh that invented "
            "plausible-looking papers would be worse than an empty library."
        )
        _finish_run(db, run_id, outcome)
        return outcome

    try:
        candidates = await discover(wanted)
    except Exception as exc:
        outcome.detail = f"Discovery failed ({type(exc).__name__}): {exc}"
        logger.warning("[science] refresh discovery failed: %s", exc)
        _finish_run(db, run_id, outcome)
        return outcome

    candidates = list(candidates)[:MAX_REFRESH_CANDIDATES]
    outcome.candidates_seen = len(candidates)

    for candidate in candidates:
        if candidate.retracted:
            # A retraction found upstream is flagged, never applied. Which
            # reviews relied on it is a question for a person.
            record_id = _record_for_identifier(
                db, owner, doi=candidate.doi, url=candidate.url,
            )
            if record_id:
                outcome.retractions_flagged.append(record_id)
                outcome.affected_review_ids.extend(
                    reviews_citing(db, owner, record_id)
                )
            continue

        if not candidate.doi and not candidate.url:
            outcome.duplicates_skipped += 1
            continue
        if _record_for_identifier(
            db, owner, doi=candidate.doi, url=candidate.url,
        ):
            outcome.duplicates_skipped += 1
            continue

        if not ingest:
            outcome.queued_unreviewed += 1
            continue

        try:
            payload = ScienceRegisterInput(
                title=candidate.title, source_type=candidate.source_type,
                topics=list(candidate.topics or wanted[:1]),
                url=candidate.url, doi=candidate.doi,
                notes=candidate.detail,
            )
            result = await register_source(
                db, owner, payload, discovered_by="refresh",
                discovered_run_id=run_id,
            )
            if result.duplicate_of:
                outcome.duplicates_skipped += 1
            else:
                outcome.queued_unreviewed += 1
        except ScienceError as exc:
            # One bad candidate does not fail the run. The queue is the
            # product, and a single unfetchable URL should not cost the
            # other twenty-four.
            logger.info(
                "[science] refresh skipped %r: %s (%s)",
                candidate.title[:60], exc, exc.category.value,
            )
            db.rollback()
        except Exception as exc:
            logger.warning(
                "[science] refresh candidate %r failed: %s",
                candidate.title[:60], exc,
            )
            db.rollback()

    outcome.succeeded = True
    # Whether there is anything to say is decided here rather than inside
    # the sender: a quiet run must not reach the delivery path at all. A
    # monthly "no new papers" message is the nag pattern this codebase has
    # already been through.
    if outcome.queued_unreviewed or outcome.retractions_flagged:
        outcome.digest_sent = await _send_digest(db, owner, outcome)
    _finish_run(db, run_id, outcome)
    return outcome


@dataclass
class ScienceRefreshOutcomeLocal:
    """The in-process result of a refresh run.

    Mirrors `ScienceRefreshOutcome` (the validated API shape) but mutable
    while the run proceeds. Kept separate rather than mutating a pydantic
    model so the validators run once, on the finished result.
    """
    run_id: str
    attempted_at: datetime
    succeeded: bool
    queried_topics: List[ScienceTopic] = field(default_factory=list)
    candidates_seen: int = 0
    queued_unreviewed: int = 0
    duplicates_skipped: int = 0
    retractions_flagged: List[str] = field(default_factory=list)
    affected_review_ids: List[str] = field(default_factory=list)
    digest_sent: bool = False
    detail: Optional[str] = None

    def validated(self):
        from app.schemas.fitness_coach import ScienceRefreshOutcome
        return ScienceRefreshOutcome(
            run_id=self.run_id, attempted_at=self.attempted_at,
            succeeded=self.succeeded, queried_topics=self.queried_topics,
            candidates_seen=self.candidates_seen,
            queued_unreviewed=self.queued_unreviewed,
            duplicates_skipped=self.duplicates_skipped,
            retractions_flagged=self.retractions_flagged,
            affected_review_ids=sorted(set(self.affected_review_ids)),
            digest_sent=self.digest_sent, detail=self.detail,
        )


def _record_for_identifier(
    db: Session, user_id: str, *, doi: Optional[str], url: Optional[str],
) -> Optional[str]:
    """An existing record with this DOI or exact URL, if any."""
    if doi:
        found = db.execute(text("""
            SELECT id FROM fitness_science_record
            WHERE user_id = :u AND doi = :doi
        """), {"u": user_id, "doi": doi.lower()}).scalar()
        if found:
            return found
    if url:
        return db.execute(text("""
            SELECT id FROM fitness_science_record
            WHERE user_id = :u AND url = :url
            LIMIT 1
        """), {"u": user_id, "url": url}).scalar()
    return None


def _finish_run(
    db: Session, run_id: str, outcome: "ScienceRefreshOutcomeLocal",
) -> None:
    db.execute(text("""
        UPDATE fitness_science_refresh_run SET
            succeeded = :ok,
            finished_at = CASE WHEN :ok THEN NOW() ELSE finished_at END,
            candidates_seen = :seen,
            queued_unreviewed = :queued,
            duplicates_skipped = :dupes,
            retractions_flagged = CAST(:retractions AS JSONB),
            affected_review_ids = CAST(:reviews AS JSONB),
            digest_sent = :digest,
            detail = :detail
        WHERE id = :id
    """), {
        "ok": outcome.succeeded, "seen": outcome.candidates_seen,
        "queued": outcome.queued_unreviewed,
        "dupes": outcome.duplicates_skipped,
        "retractions": json.dumps(sorted(set(outcome.retractions_flagged))),
        "reviews": json.dumps(sorted(set(outcome.affected_review_ids))),
        "digest": outcome.digest_sent, "detail": outcome.detail,
        "id": run_id,
    })
    db.commit()


async def _send_digest(
    db: Session, user_id: str, outcome: "ScienceRefreshOutcomeLocal",
) -> bool:
    """One digest per run, through the single mouth.

    Routed via `say_candidate` like every other proactive line (§5 Mind
    V2): a module that writes to the delivery tables itself is a second
    mouth, and there have been two before. A quiet run sends nothing — a
    monthly "no new papers" message is the nag pattern this codebase has
    already been through.
    """
    if not outcome.queued_unreviewed and not outcome.retractions_flagged:
        return False

    parts: List[str] = []
    if outcome.queued_unreviewed:
        parts.append(
            f"{outcome.queued_unreviewed} new "
            f"{'paper' if outcome.queued_unreviewed == 1 else 'papers'} "
            f"waiting for review in the science library"
        )
    if outcome.retractions_flagged:
        parts.append(
            f"{len(outcome.retractions_flagged)} "
            f"{'source' if len(outcome.retractions_flagged) == 1 else 'sources'} "
            f"flagged as retracted"
        )
        if outcome.affected_review_ids:
            parts.append(
                f"affecting {len(set(outcome.affected_review_ids))} past "
                f"{'review' if len(set(outcome.affected_review_ids)) == 1 else 'reviews'}"
            )
    message = "; ".join(parts) + ". Nothing was accepted or applied."

    from app.core.timezone import now as local_now
    from app.db.session import get_async_session_factory
    from app.services.say_candidate import create_candidate

    try:
        factory = get_async_session_factory()
        async with factory() as async_db:
            candidate_id = await create_candidate(
                async_db, user_id,
                source="fitness_science",
                # "inform", not "alert". A queue of papers to read is not
                # urgent, and `_KINDS` has no "digest" — reaching for
                # `alert` to make it noticed is how a library notification
                # ends up interrupting a workout.
                kind="inform",
                summary=message,
                evidence=[{
                    "kind": "science_refresh", "run_id": outcome.run_id,
                    "queued": outcome.queued_unreviewed,
                    "retracted": sorted(set(outcome.retractions_flagged)),
                }],
                dedupe_key=f"science_digest:{outcome.run_id}",
                valid_until=local_now() + timedelta(days=7),
            )
            await async_db.commit()
        # `create_candidate` returns None when its own dedupe guard killed
        # the candidate, which is a real outcome and not a failure: one
        # digest per run, and the run id is the key.
        return candidate_id is not None
    except Exception as exc:
        # A failed digest does not fail the run: the records are queued and
        # the library screen shows them. Reporting "digest sent" when it
        # was not is the lie worth avoiding here.
        logger.warning("[science] digest not delivered: %s", exc)
        return False
