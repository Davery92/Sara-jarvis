"""Running a vision model over a photo the athlete explicitly consented to.

FITNESS_COACH_IMPLEMENTATION_PLAN Step 27. Completion criteria: a VERIFIED
vision capability with structured uncertainty output; no precise composition
or diagnostic claims; consent, isolation and audit enforced.

The order of operations is the design:

    consent  →  owner check  →  fetch bytes  →  call (no transaction held)
    →  validate  →  reject or store

Consent first, before the bytes are even read. Reading somebody's photo out
of object storage to decide whether we are allowed to read it is the wrong
way round, and the owner check comes before the fetch for the same reason.

**The endpoint must be verified.** §27.1 is explicit that Qwen's text lane
cannot be assumed to handle multimodal input, and the failure is silent: a
`llama.cpp` server started without `--mmproj` serves the same model over the
same API, ignores the image part, and answers the text prompt alone. That
reads as a model with poor vision. `scripts/fitness_vision_probe.py` draws a
synthetic coloured shape and checks the answer names it; this module refuses
to run against an endpoint that has not passed, and records which endpoint
answered on every row.

**No cloud fallback.** §27.5: default no cloud fallback, and an explicit
user-approved image provider policy before any. There is no policy yet, so
there is no fallback — an unavailable local endpoint is a failed analysis,
not a reason to send somebody's body to an API.

**A failure never blocks the upload.** §27.5 again. The photo is already
stored and listed; an analysis is an opinion about it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.prompts import fitness_photo_observations as prompts
from app.schemas.fitness_coach import (
    PhotoAnalysisFailure,
    PhotoAnalysisStatus,
    PhotoComparisonV1,
    PhotoObservationV1,
)
from app.services.fitness.data_access import FitnessDataError, _require_user

logger = logging.getLogger(__name__)

#: One repair turn. A model that cannot produce the schema twice will not
#: produce it on the fifth attempt, and each attempt is GPU time and a wait.
MAX_REPAIR_ATTEMPTS = 1

#: End to end for one call. Vision on the A3B lane answered a synthetic
#: probe in well under a second; a physique photo with a real prompt is
#: seconds, so a minute is generous and still bounded.
CALL_TIMEOUT = 90.0


class AnalysisRefused(FitnessDataError):
    """A precondition failed: no consent, no capability, wrong owner."""

    def __init__(self, message: str, category: PhotoAnalysisFailure):
        super().__init__(message)
        self.category = category


@dataclass
class AnalysisResult:
    analysis_id: str
    status: PhotoAnalysisStatus
    output: Optional[Any] = None
    failure_category: Optional[PhotoAnalysisFailure] = None
    detail: Optional[str] = None
    model_actual: Optional[str] = None
    duplicate: bool = False


# ─────────────────────────────────────────────────────────────────────────
# Capability
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class VisionCapability:
    endpoint: str
    model: str
    transport: str
    verified: bool
    detail: str = ""


def resolve_capability(db: Session, user_id: str) -> VisionCapability:
    """Which endpoint and model would actually be used, and whether it sees.

    Resolved EXPLICITLY from the athlete's `UserSettings` and then the
    config, because the two defaults in this codebase disagree:
    `routes/vision.py` points at an Ollama on :11434 and
    `core/llm_config.py` at a llama-server on :8686. Only one answers, and a
    module that assumed either would be right half the time.

    `verified` comes from the probe cache, not from the endpoint's own
    claim. A server advertising `multimodal` in `/v1/models` while running
    without `--mmproj` is exactly the case the probe exists to catch.
    """
    endpoint = None
    model = None
    try:
        row = db.execute(text("""
            SELECT vision_endpoint, vision_model FROM user_settings
            WHERE user_id = :uid
        """), {"uid": user_id}).fetchone()
        if row is not None:
            endpoint = row.vision_endpoint or None
            model = row.vision_model or None
    except Exception as exc:
        logger.debug(
            "user vision settings unavailable (%s)", type(exc).__name__,
        )

    if not endpoint or not model:
        from app.core.llm_config import llm_config
        endpoint = endpoint or str(llm_config.vision_url)
        model = model or str(llm_config.vision_model)

    verified, detail = _probe_cache(endpoint, model)
    return VisionCapability(
        endpoint=endpoint, model=model,
        # Only the OpenAI-compatible transport is used here: it is the one
        # the probe verified, and the Ollama default is not answering.
        transport="openai",
        verified=verified, detail=detail,
    )


#: Verified endpoints, from `scripts/fitness_vision_probe.py`.
#:
#: A static allowlist rather than a live probe per analysis: probing on every
#: call would add a round trip to each one, and the thing being checked —
#: whether the server was started with `--mmproj` — changes only when the
#: server restarts. Re-run the probe after a restart and update this.
#:
#:   2026-10-02: http://10.185.1.8:8686 / qwen3.6-35b-a3b answered
#:   "Red circle" and "Blue triangle" to synthetic shapes in ~0.6s.
#:   http://10.185.1.8:11434 (the Ollama default in routes/vision.py) does
#:   not accept connections at all.
VERIFIED_VISION: Dict[Tuple[str, str], str] = {
    ("http://10.185.1.8:8686", "qwen3.6-35b-a3b"):
        "probed 2026-10-02: named a red circle and a blue triangle",
}


def _probe_cache(endpoint: str, model: str) -> Tuple[bool, str]:
    key = (endpoint.rstrip("/"), model)
    if key in VERIFIED_VISION:
        return True, VERIFIED_VISION[key]
    return False, (
        f"{endpoint} / {model} has not passed "
        f"scripts/fitness_vision_probe.py. A server without --mmproj serves "
        f"the same model over the same API and silently ignores the image, "
        f"so an unverified endpoint produces text that looks like an "
        f"observation and is not one."
    )


# ─────────────────────────────────────────────────────────────────────────
# Preconditions
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class PhotoRow:
    id: str
    user_id: str
    storage_key: str
    view: Optional[str]
    taken_at: Optional[datetime]
    lighting: Optional[str]
    distance_cm: Optional[int]
    capture_protocol: Optional[str]
    content_sha256: Optional[str]
    consent_analysis: bool


def load_photo(db: Session, user_id: str, photo_id: str) -> PhotoRow:
    """The owner check. Before any bytes are fetched.

    Fetching somebody's photo out of object storage to decide whether we are
    allowed to look at it is the wrong way round.
    """
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, user_id, storage_key, view, taken_at, lighting,
               distance_cm, capture_protocol, content_sha256,
               consent_analysis
        FROM progress_photo
        WHERE id = :id AND user_id = :uid AND deleted_at IS NULL
    """), {"id": photo_id, "uid": uid}).fetchone()
    if row is None:
        # 404 for a foreign, missing or deleted id. Never 403.
        raise LookupError("progress photo not found")
    return PhotoRow(**dict(row._mapping))


def require_consent(photo: PhotoRow) -> None:
    """Explicit consent, per photo. Default false.

    Uploading a photo is a record the athlete wanted kept. It is not
    permission for a model to look at their body, and treating it as such is
    the difference between a feature and a violation.
    """
    if not photo.consent_analysis:
        raise AnalysisRefused(
            "that photo has no analysis consent. Uploading it is not "
            "permission to run a model over it.",
            PhotoAnalysisFailure.NO_CONSENT,
        )


# ─────────────────────────────────────────────────────────────────────────
# The analysis
# ─────────────────────────────────────────────────────────────────────────

def open_analysis(
    db: Session,
    user_id: str,
    *,
    source: PhotoRow,
    compare: Optional[PhotoRow] = None,
    capability: VisionCapability,
    capture_hash: str,
) -> Tuple[str, bool]:
    """Claim the analysis row, or return the existing one.

    Idempotent on `(user, kind, source, compare, prompt_version,
    capture_hash)`. `capture_hash` is in the key so a replaced image is a
    NEW analysis rather than a silent reuse of a description of other pixels.
    """
    uid = _require_user(user_id)
    kind = "pair" if compare is not None else "single"
    analysis_id = str(uuid.uuid4())

    inserted = db.execute(text("""
        INSERT INTO fitness_photo_analysis (
            id, user_id, kind, source_photo_id, compare_photo_id, view,
            source_captured_at, compare_captured_at, capture_hash, status,
            model_requested, provider, endpoint, vision_verified,
            prompt_version, prompt_hash, attempts
        ) VALUES (
            :id, :uid, :kind, :src, :cmp, :view, :src_at, :cmp_at, :hash,
            'pending', :model, 'local', :endpoint, :verified,
            :prompt_v, :prompt_h, 0
        )
        ON CONFLICT (user_id, kind, source_photo_id,
                     COALESCE(compare_photo_id, ''), prompt_version,
                     COALESCE(capture_hash, ''))
        DO NOTHING
        RETURNING id
    """), {
        "id": analysis_id, "uid": uid, "kind": kind,
        "src": source.id, "cmp": compare.id if compare else None,
        "view": (compare or source).view or source.view,
        "src_at": source.taken_at,
        "cmp_at": compare.taken_at if compare else None,
        "hash": capture_hash,
        "model": capability.model, "endpoint": capability.endpoint,
        "verified": capability.verified,
        "prompt_v": prompts.PROMPT_VERSION,
        "prompt_h": hashlib.sha256(
            prompts.prompt_text().encode("utf-8")
        ).hexdigest(),
    }).fetchone()

    if inserted is not None:
        return analysis_id, False

    existing = db.execute(text("""
        SELECT id FROM fitness_photo_analysis
        WHERE user_id = :uid AND kind = :kind AND source_photo_id = :src
          AND COALESCE(compare_photo_id, '') = COALESCE(:cmp, '')
          AND prompt_version = :prompt_v
          AND COALESCE(capture_hash, '') = COALESCE(:hash, '')
    """), {
        "uid": uid, "kind": kind, "src": source.id,
        "cmp": compare.id if compare else None,
        "prompt_v": prompts.PROMPT_VERSION, "hash": capture_hash,
    }).fetchone()
    if existing is None:  # pragma: no cover - the conflict just happened
        raise FitnessDataError("the analysis conflicted but could not be read")
    return existing.id, True


async def analyse_photo(
    db: Session,
    user_id: str,
    photo_id: str,
    *,
    compare_photo_id: Optional[str] = None,
) -> AnalysisResult:
    """One analysis, to a terminal state.

    Every exit is terminal. A row left `running` because a worker died is
    the one state nothing can interpret: the UI spins and the idempotency
    key refuses a replacement.
    """
    uid = _require_user(user_id)

    source = load_photo(db, uid, photo_id)
    compare = (
        load_photo(db, uid, compare_photo_id) if compare_photo_id else None
    )
    if compare is not None and compare.id == source.id:
        raise FitnessDataError(
            "a photo cannot be compared with itself; the answer would be "
            "'identical' and it would look like a finding"
        )

    require_consent(source)
    if compare is not None:
        require_consent(compare)

    capability = resolve_capability(db, uid)
    capture_hash = _capture_hash(source, compare)
    analysis_id, duplicate = open_analysis(
        db, uid, source=source, compare=compare,
        capability=capability, capture_hash=capture_hash,
    )
    db.commit()

    if duplicate:
        stored = get_analysis(db, uid, analysis_id)
        if stored["status"] not in ("pending", "running"):
            return AnalysisResult(
                analysis_id=analysis_id,
                status=PhotoAnalysisStatus(stored["status"]),
                output=stored.get("output"),
                model_actual=stored.get("model_actual"),
                duplicate=True,
            )

    if not capability.verified:
        # §27.1. An unverified endpoint produces text that looks like an
        # observation and is not one, so nothing is stored as output.
        _fail(
            db, uid, analysis_id,
            PhotoAnalysisFailure.NO_VISION_CAPABILITY, capability.detail,
        )
        db.commit()
        return AnalysisResult(
            analysis_id=analysis_id, status=PhotoAnalysisStatus.FAILED,
            failure_category=PhotoAnalysisFailure.NO_VISION_CAPABILITY,
            detail=capability.detail,
        )

    _mark_running(db, uid, analysis_id)
    db.commit()

    # Bytes fetched AFTER consent and the owner check, and outside any
    # transaction — a vision call can take seconds and the fitness lane
    # shares its connection pool with chat.
    try:
        images = _fetch_images(source, compare)
    except Exception as exc:
        logger.warning(
            "photo bytes unreadable for analysis %s (%s): %s",
            analysis_id, type(exc).__name__, exc,
        )
        _fail(
            db, uid, analysis_id, PhotoAnalysisFailure.IMAGE_UNREADABLE,
            f"{type(exc).__name__}: {exc}",
        )
        db.commit()
        return AnalysisResult(
            analysis_id=analysis_id, status=PhotoAnalysisStatus.FAILED,
            failure_category=PhotoAnalysisFailure.IMAGE_UNREADABLE,
        )

    try:
        output, model_actual, errors = await _call_and_validate(
            capability, source, compare, images,
        )
    except Exception as exc:
        category = _transport_category(exc)
        _fail(db, uid, analysis_id, category, f"{type(exc).__name__}: {exc}")
        db.commit()
        return AnalysisResult(
            analysis_id=analysis_id, status=PhotoAnalysisStatus.FAILED,
            failure_category=category,
        )

    if output is None:
        category = (
            PhotoAnalysisFailure.BODY_COMPOSITION_CLAIM
            if any("body-composition number" in e for e in errors)
            else PhotoAnalysisFailure.INVALID_OUTPUT
        )
        _fail(db, uid, analysis_id, category, "; ".join(errors))
        db.commit()
        return AnalysisResult(
            analysis_id=analysis_id, status=PhotoAnalysisStatus.FAILED,
            failure_category=category, detail="; ".join(errors)[:400],
            model_actual=model_actual,
        )

    # The source must still be the image that was analysed. A photo deleted
    # or replaced mid-run would otherwise leave a description of pixels
    # nobody can see.
    if not _source_unchanged(db, uid, source, compare, capture_hash):
        _terminal(
            db, uid, analysis_id, PhotoAnalysisStatus.SOURCE_GONE,
            PhotoAnalysisFailure.SOURCE_CHANGED,
            "the photo was deleted or replaced while this was running",
        )
        db.commit()
        return AnalysisResult(
            analysis_id=analysis_id, status=PhotoAnalysisStatus.SOURCE_GONE,
            failure_category=PhotoAnalysisFailure.SOURCE_CHANGED,
        )

    status = PhotoAnalysisStatus.COMPLETE
    if isinstance(output, PhotoComparisonV1) and \
            output.verdict.value != "comparable":
        # A refusal to compare is its own terminal state, not a failure:
        # "these two cannot be compared" is frequently the only honest
        # reading, and calling it failed would invite a retry.
        status = PhotoAnalysisStatus.INCONCLUSIVE

    _complete(db, uid, analysis_id, output, model_actual, status)
    db.commit()
    return AnalysisResult(
        analysis_id=analysis_id, status=status, output=output,
        model_actual=model_actual,
    )


def _capture_hash(source: PhotoRow, compare: Optional[PhotoRow]) -> str:
    """A fingerprint of the exact bytes being analysed.

    Falls back to the storage keys when `content_sha256` is absent (rows
    that predate Step 26). Weaker, but it still changes when the stored
    object changes, which is what the key needs.
    """
    parts = [source.content_sha256 or source.storage_key]
    if compare is not None:
        parts.append(compare.content_sha256 or compare.storage_key)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _source_unchanged(
    db: Session, user_id: str, source: PhotoRow,
    compare: Optional[PhotoRow], capture_hash: str,
) -> bool:
    ids = [source.id] + ([compare.id] if compare else [])
    rows = db.execute(text("""
        SELECT id, content_sha256, storage_key, deleted_at
        FROM progress_photo
        WHERE id = ANY(:ids) AND user_id = :uid
    """), {"ids": ids, "uid": user_id}).fetchall()
    if len(rows) != len(ids):
        return False
    by_id = {r.id: r for r in rows}
    if any(by_id[i].deleted_at is not None for i in ids):
        return False
    rebuilt = [
        by_id[source.id].content_sha256 or by_id[source.id].storage_key
    ]
    if compare is not None:
        rebuilt.append(
            by_id[compare.id].content_sha256 or by_id[compare.id].storage_key
        )
    return hashlib.sha256(
        "|".join(rebuilt).encode("utf-8")
    ).hexdigest() == capture_hash


def _fetch_images(
    source: PhotoRow, compare: Optional[PhotoRow],
) -> List[str]:
    """Base64 the stored objects. Nothing is written back.

    The bytes never touch the database: `fitness_photo_analysis` holds no
    image column, because a copy there would be a second place to leak a
    photo from.
    """
    from app.services.docs_ingest import DocumentProcessor

    processor = DocumentProcessor()
    keys = [source.storage_key] + (
        [compare.storage_key] if compare is not None else []
    )
    return [
        base64.b64encode(processor.get_file(key)).decode("ascii")
        for key in keys
    ]


async def _call_and_validate(
    capability: VisionCapability,
    source: PhotoRow,
    compare: Optional[PhotoRow],
    images: List[str],
) -> Tuple[Optional[Any], Optional[str], List[str]]:
    """One call, then at most one repair."""
    is_pair = compare is not None
    system = (
        prompts.PAIR_SYSTEM_PROMPT if is_pair
        else prompts.SINGLE_SYSTEM_PROMPT
    )
    if is_pair:
        user_prompt = prompts.build_pair_user_prompt(
            view=(source.view or "other"),
            earlier=_capture_context(source),
            later=_capture_context(compare),
        )
    else:
        user_prompt = prompts.build_single_user_prompt(
            view=source.view or "other",
            taken_on=(
                source.taken_at.date().isoformat() if source.taken_at else None
            ),
            lighting=source.lighting,
            distance_cm=source.distance_cm,
            protocol=source.capture_protocol,
        )

    content, model_actual = await _chat(capability, system, user_prompt, images)
    output, errors = _parse(content, is_pair=is_pair)
    if output is not None:
        return output, model_actual, []

    for _ in range(MAX_REPAIR_ATTEMPTS):
        repair = user_prompt + "\n\n" + prompts.build_repair_prompt(errors)
        content, repair_model = await _chat(
            capability, system, repair, images,
        )
        model_actual = repair_model or model_actual
        output, repair_errors = _parse(content, is_pair=is_pair)
        if output is not None:
            return output, model_actual, []
        errors = errors + repair_errors
    return None, model_actual, errors


def _capture_context(photo: PhotoRow) -> Dict[str, Any]:
    return {
        "taken_on": (
            photo.taken_at.date().isoformat() if photo.taken_at else None
        ),
        "lighting": photo.lighting,
        "distance_cm": photo.distance_cm,
        "capture_protocol": photo.capture_protocol,
    }


async def _chat(
    capability: VisionCapability,
    system: str,
    user_prompt: str,
    images: List[str],
) -> Tuple[str, Optional[str]]:
    """One bounded multimodal call, local only.

    `call_openai_vision` takes a single image, so a pair goes through a
    hand-built request with two `image_url` parts — which is the shape the
    probe verified against this endpoint.

    No cloud fallback (§27.5). An unavailable local endpoint is a failed
    analysis, not a reason to send somebody's body to an API.
    """
    import httpx

    base = capability.endpoint.rstrip("/")
    url = f"{base}/chat/completions" if base.endswith("/v1") \
        else f"{base}/v1/chat/completions"

    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image}"},
        })

    body = {
        "model": capability.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": prompts.TEMPERATURE,
        "max_tokens": prompts.MAX_OUTPUT_TOKENS,
        # Qwen returns an empty `content` for structured output with
        # thinking on (§9). Nested, where the template actually reads it.
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": False,
    }

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=CALL_TIMEOUT) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        payload = response.json()
    elapsed = time.monotonic() - started

    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    answer = (message.get("content") or "").strip()
    # `reasoning_content` is deliberately NOT used as a fallback here, which
    # is what `routes/vision.py` does for screenshots. A chain-of-thought
    # about somebody's body is private musing, and §27 says not to store
    # hidden reasoning — salvaging it as the answer would store it.
    model_actual = payload.get("model") or capability.model
    logger.info(
        "[fitness-photo] model=%s images=%d %.1fs",
        model_actual, len(images), elapsed,
    )
    if not answer:
        raise ValueError("the vision model returned no parseable content")
    return answer, model_actual


def _parse(
    content: str, *, is_pair: bool,
) -> Tuple[Optional[Any], List[str]]:
    """Tolerant about the wrapper, strict about the content."""
    raw = _extract_json(content)
    if raw is None:
        return None, ["the output contained no JSON object"]
    model = PhotoComparisonV1 if is_pair else PhotoObservationV1
    try:
        return model.model_validate(raw), []
    except Exception as exc:
        return None, [_short_error(exc)]


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    stripped = (content or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _short_error(exc: Exception) -> str:
    """Compact, and without echoing the model's text.

    Pydantic's full payload quotes the input, which would put a rejected
    description of somebody's body into `failure_detail` — a column that
    deliberately holds no observations.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            parts = []
            for item in errors()[:6]:
                location = ".".join(str(p) for p in item.get("loc", ()))
                parts.append(f"{location}: {item.get('msg')}")
            return "; ".join(parts)[:400] or str(exc)[:300]
        except Exception:
            pass
    return str(exc)[:300]


def _transport_category(exc: Exception) -> PhotoAnalysisFailure:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return PhotoAnalysisFailure.MODEL_TIMEOUT
    if "connect" in name or "connection" in name or "unreachable" in message:
        return PhotoAnalysisFailure.MODEL_UNAVAILABLE
    if "no parseable content" in message:
        return PhotoAnalysisFailure.MODEL_UNAVAILABLE
    return PhotoAnalysisFailure.INTERNAL_ERROR


# ─────────────────────────────────────────────────────────────────────────
# State transitions
# ─────────────────────────────────────────────────────────────────────────

def _mark_running(db: Session, user_id: str, analysis_id: str) -> None:
    db.execute(text("""
        UPDATE fitness_photo_analysis
        SET status = 'running', attempts = attempts + 1, updated_at = NOW()
        WHERE id = :id AND user_id = :uid
          AND status IN ('pending', 'running')
    """), {"id": analysis_id, "uid": user_id})


def _fail(
    db: Session, user_id: str, analysis_id: str,
    category: PhotoAnalysisFailure, detail: str,
) -> None:
    _terminal(
        db, user_id, analysis_id, PhotoAnalysisStatus.FAILED, category, detail,
    )


def _terminal(
    db: Session, user_id: str, analysis_id: str,
    status: PhotoAnalysisStatus, category: Optional[PhotoAnalysisFailure],
    detail: Optional[str],
) -> None:
    db.execute(text("""
        UPDATE fitness_photo_analysis
        SET status = :status, failure_category = :cat, failure_detail = :detail,
            evaluated_at = NOW(), updated_at = NOW()
        WHERE id = :id AND user_id = :uid
          AND status NOT IN ('complete', 'failed', 'inconclusive',
                             'source_gone')
    """), {
        "id": analysis_id, "uid": user_id, "status": status.value,
        "cat": category.value if category else None,
        "detail": (detail or "")[:500] or None,
    })


def _complete(
    db: Session, user_id: str, analysis_id: str, output: Any,
    model_actual: Optional[str], status: PhotoAnalysisStatus,
) -> None:
    db.execute(text("""
        UPDATE fitness_photo_analysis
        SET status = :status, output = CAST(:output AS jsonb),
            summary = :summary, model_actual = :model,
            output_schema_version = :version,
            evaluated_at = NOW(), updated_at = NOW()
        WHERE id = :id AND user_id = :uid
          AND status NOT IN ('complete', 'failed', 'inconclusive',
                             'source_gone')
    """), {
        "id": analysis_id, "uid": user_id, "status": status.value,
        "output": output.model_dump_json(),
        "summary": output.summary,
        "model": model_actual,
        "version": output.output_version,
    })
    # Mirror onto the photo so a gallery can show the state without a join.
    db.execute(text("""
        UPDATE progress_photo SET analysis_status = :status, updated_at = NOW()
        WHERE id = (
            SELECT source_photo_id FROM fitness_photo_analysis WHERE id = :id
        ) AND user_id = :uid
    """), {"status": status.value, "id": analysis_id, "uid": user_id})


# ─────────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────────

def get_analysis(db: Session, user_id: str, analysis_id: str) -> Dict[str, Any]:
    uid = _require_user(user_id)
    row = db.execute(text("""
        SELECT id, kind, source_photo_id, compare_photo_id, view, status,
               model_actual, endpoint, vision_verified, prompt_version,
               output, summary, failure_category, failure_detail,
               attempts, evaluated_at, created_at
        FROM fitness_photo_analysis
        WHERE id = :id AND user_id = :uid
    """), {"id": analysis_id, "uid": uid}).fetchone()
    if row is None:
        raise LookupError("photo analysis not found")
    return dict(row._mapping)


def list_analyses(
    db: Session, user_id: str, *, photo_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    uid = _require_user(user_id)
    clauses = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": uid, "lim": max(1, min(limit, 100))}
    if photo_id:
        clauses.append(
            "(source_photo_id = :pid OR compare_photo_id = :pid)"
        )
        params["pid"] = photo_id
    rows = db.execute(text(f"""
        SELECT id, kind, source_photo_id, compare_photo_id, view, status,
               model_actual, summary, failure_category, created_at
        FROM fitness_photo_analysis
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT :lim
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


def validated_observations(
    db: Session, user_id: str, *, limit: int = 5,
) -> List[Dict[str, Any]]:
    """What `FitnessStateV1` may summarise: VALIDATED observations only.

    A failed analysis contributes nothing, and the legacy free-text critique
    is excluded entirely — §27.4. It was written by a prompt that asked for
    a body-fat estimate, so it is not an observation and must never reach a
    numeric or composition field.
    """
    uid = _require_user(user_id)
    rows = db.execute(text("""
        SELECT id, kind, view, summary, status, evaluated_at,
               output -> 'confidence' AS confidence,
               output -> 'image_quality' AS image_quality,
               output -> 'verdict' AS verdict
        FROM fitness_photo_analysis
        WHERE user_id = :uid AND status IN ('complete', 'inconclusive')
          AND output IS NOT NULL
        ORDER BY evaluated_at DESC NULLS LAST
        LIMIT :lim
    """), {"uid": uid, "lim": max(1, min(limit, 20))}).fetchall()
    return [dict(r._mapping) for r in rows]
