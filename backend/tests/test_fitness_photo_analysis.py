"""Step 27 of FITNESS_COACH_IMPLEMENTATION_PLAN: structured photo
observations with honest uncertainty, and no composition claims.

The three completion criteria:

* **Verified vision capability with structured uncertainty output.** The
  capability is a probe result, not an endpoint's own claim: a `llama.cpp`
  server started without `--mmproj` serves the same model over the same API,
  silently ignores the image and answers the text prompt alone — which reads
  as a model with poor eyesight. `scripts/fitness_vision_probe.py` draws a
  coloured shape and checks the answer names it; the real roundtrip at the
  bottom of this file is the one that proves deployed capability.
* **No precise composition or diagnostic claims.** Three layers, because the
  prompt alone has never been enough: the prompt forbids it, the schema has
  no field for it, and the validator rejects it in prose.
* **Consent, isolation and audit enforced.** Consent is checked before the
  bytes are fetched, a pair cannot span two athletes, and the stored row is
  immutable once terminal.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_photo_analysis.py
"""
import asyncio
import base64
import io
import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────
# The output schema refuses body composition
# ─────────────────────────────────────────────────────────────────────────

def _observation(**over):
    from app.schemas.fitness_coach import PhotoObservationV1
    body = {
        "view": "front",
        "summary": "Shoulders read wider than the waist; lats visible.",
        "regions": [],
        "limitations": ["The midsection is in shadow."],
        "image_quality": "good",
        "pose_consistent_with_view": True,
        "confidence": "moderate",
        "confidence_basis": "clear lighting and a square-on pose",
    }
    body.update(over)
    return PhotoObservationV1(**body)


def _comparison(**over):
    from app.schemas.fitness_coach import PhotoComparisonV1
    body = {
        "view": "front",
        "verdict": "comparable",
        "summary": "Shoulders look slightly wider in the later photo.",
        "regions": [],
        "limitations": [],
        "capture_consistent": True,
        "image_quality": "good",
        "confidence": "low",
        "confidence_basis": "same lighting and distance, four weeks apart",
    }
    body.update(over)
    return PhotoComparisonV1(**body)


def test_a_clean_observation_validates():
    assert _observation().view.value == "front"


def test_the_schema_has_no_body_composition_field():
    """§5.5: "no body-fat percentage field or diagnosis". A field for one
    guarantees a model fills it."""
    from app.schemas.fitness_coach import PhotoComparisonV1, PhotoObservationV1

    for model in (PhotoObservationV1, PhotoComparisonV1):
        fields = set(model.model_fields)
        for forbidden in ("body_fat", "body_fat_percent", "bf", "lean_mass",
                          "estimated_weight", "weight", "bmi", "measurements"):
            assert forbidden not in fields, (model.__name__, forbidden)


@pytest.mark.parametrize("text_value", [
    "Looks about 14% body fat.",
    "I'd estimate 12-15% body fat here.",
    "Body fat around 18.",
    "Roughly 85 kg, judging by the frame.",
    "Probably 190 lbs at this point.",
    "Lean mass looks like 70 kg.",
    "BMI appears to be in the normal range.",
])
def test_a_composition_number_in_prose_is_rejected(text_value):
    """The schema has nowhere to put one, so a model that wants to say it
    puts it in the summary — where it reads as an observation and
    `health_metric` never sees it."""
    with pytest.raises(Exception) as excinfo:
        _observation(summary=text_value)
    assert "body-composition number" in str(excinfo.value)


def test_a_composition_number_in_a_region_is_rejected_too():
    from app.schemas.fitness_coach import RegionObservation

    with pytest.raises(Exception):
        _observation(regions=[RegionObservation(
            region="midsection",
            observation="Looks like 15% body fat around here.",
            confidence="low",
        )])


def test_a_composition_number_in_a_limitation_is_rejected_too():
    with pytest.raises(Exception):
        _observation(limitations=["Hard to tell past about 12% body fat."])


def test_a_qualitative_description_is_allowed():
    """The whole point is that the useful statements still pass."""
    for summary in (
        "Leaner through the midsection than the earlier shot.",
        "Shoulders read wider relative to the waist.",
        "Vascularity visible in the forearms.",
        "Lighting makes the abdominal detail hard to read.",
    ):
        assert _observation(summary=summary)


def test_a_rep_count_or_a_date_is_not_mistaken_for_a_body_number():
    """The check must not fire on ordinary text, or every observation fails
    and the feature is an outage."""
    for summary in (
        "Taken 4 weeks after the 2026-09-01 photo.",
        "Three regions are visible in this one.",
        "The same pose as photo 2.",
    ):
        assert _observation(summary=summary)


def test_a_comparison_must_say_why_it_is_inconclusive():
    """A refusal with no reason is indistinguishable from a failure."""
    with pytest.raises(Exception) as excinfo:
        _comparison(verdict="inconclusive", inconclusive_reason=None)
    assert "must say why" in str(excinfo.value)


def test_an_inconclusive_comparison_with_a_reason_validates():
    result = _comparison(
        verdict="inconclusive", capture_consistent=False,
        inconclusive_reason=(
            "the first is lit from a window and the second overhead"
        ),
    )
    assert result.verdict.value == "inconclusive"


def test_a_comparable_verdict_cannot_sit_on_inconsistent_captures():
    """That combination is the definition of inconclusive, and allowing it
    would let a confident difference rest on two incomparable photos."""
    with pytest.raises(Exception) as excinfo:
        _comparison(verdict="comparable", capture_consistent=False)
    assert "definition of inconclusive" in str(excinfo.value)


def test_image_quality_and_confidence_are_separate_fields():
    """A clear photo can support only a weak statement, and a confident
    reading of a badly lit one must stay visible as two facts."""
    result = _observation(image_quality="poor", confidence="high")
    assert result.image_quality.value == "poor"
    assert result.confidence.value == "high"


def test_an_invented_field_is_rejected():
    from app.schemas.fitness_coach import PhotoObservationV1

    body = json.loads(_observation().model_dump_json())
    body["body_fat_estimate"] = 14.0
    with pytest.raises(Exception):
        PhotoObservationV1.model_validate(body)


# ─────────────────────────────────────────────────────────────────────────
# The prompt
# ─────────────────────────────────────────────────────────────────────────

def test_the_prompt_forbids_every_body_number():
    from app.prompts import fitness_photo_observations as prompts

    lowered = prompts.SINGLE_SYSTEM_PROMPT.lower()
    assert "never state or estimate a body-fat percentage" in lowered
    assert "not a range, not an approximation" in lowered
    assert "never diagnose" in lowered


def test_the_pair_prompt_says_inconclusive_is_expected():
    """Otherwise the model reaches for a difference to justify its
    existence, and lighting supplies one."""
    from app.prompts import fitness_photo_observations as prompts

    lowered = prompts.PAIR_SYSTEM_PROMPT.lower()
    assert "expected answer, not a failure" in lowered
    assert "lighting, pose and camera distance" in lowered


def test_the_prompt_is_versioned_and_hashable():
    from app.prompts import fitness_photo_observations as prompts

    assert prompts.PROMPT_VERSION
    assert prompts.MAX_OUTPUT_TOKENS <= 2048
    assert prompts.TEMPERATURE <= 0.3
    assert prompts.prompt_text() == prompts.prompt_text()


def test_the_user_prompt_carries_no_owner_and_no_weight():
    """The owner id is the one field that identifies whose body this is, and
    a weight would let the model anchor a composition claim to it."""
    from app.prompts import fitness_photo_observations as prompts

    rendered = prompts.build_single_user_prompt(
        view="front", taken_on="2026-09-28", lighting="window daylight",
        distance_cm=200,
    )
    assert "window daylight" in rendered
    assert "user" not in rendered.lower()
    assert "weight" not in rendered.lower()
    assert "kg" not in rendered.lower()


def test_the_repair_prompt_says_to_remove_a_number_not_rephrase_it():
    from app.prompts import fitness_photo_observations as prompts

    rendered = prompts.build_repair_prompt(["summary: body-composition number"])
    assert "REMOVE the claim" in rendered
    assert "no acceptable way to state one" in rendered


# ─────────────────────────────────────────────────────────────────────────
# Capability must be verified
# ─────────────────────────────────────────────────────────────────────────

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
    alice = f"s27a-{uuid.uuid4().hex[:17]}"
    bob = f"s27b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s27.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_photo_analysis", "progress_photo",
                  "user_settings", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _photo(pg, uid, *, view="front", consent=True, key=None, sha=None):
    photo_id = str(uuid.uuid4())
    pg.execute(text("""
        INSERT INTO progress_photo
            (id, user_id, storage_key, mime_type, view, lighting,
             distance_cm, content_sha256, consent_analysis,
             consent_analysis_at, taken_at, created_at)
        VALUES (:id, :u, :k, 'image/jpeg', :v, 'window daylight', 200,
                :sha, :consent,
                CASE WHEN :consent THEN NOW() ELSE NULL END, NOW(), NOW())
    """), {
        "id": photo_id, "u": uid, "k": key or f"key-{photo_id}",
        "v": view, "sha": sha or uuid.uuid4().hex, "consent": consent,
    })
    pg.commit()
    return photo_id


@requires_pg
def test_an_unverified_endpoint_is_refused_and_recorded(pg, two_athletes, monkeypatch):
    """§27.1. A server without `--mmproj` answers the text prompt alone, so
    its output looks like an observation and is not one."""
    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)

    monkeypatch.setattr(
        photo_analysis, "VERIFIED_VISION", {},
    )
    called = []
    async def should_not_run(*args, **kwargs):
        called.append(True)
        raise AssertionError("the model was called on an unverified endpoint")
    monkeypatch.setattr(photo_analysis, "_chat", should_not_run)

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.status.value == "failed"
    assert result.failure_category is PhotoAnalysisFailure.NO_VISION_CAPABILITY
    assert called == []
    assert "--mmproj" in (result.detail or "")

    row = pg.execute(text("""
        SELECT vision_verified, output, failure_category
        FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).fetchone()
    assert row.vision_verified is False
    assert row.output is None


@requires_pg
def test_the_capability_resolves_the_athletes_own_settings_first(pg, two_athletes):
    """The two defaults in this codebase disagree — `routes/vision.py` points
    at an Ollama on :11434 and `llm_config` at a llama-server on :8686 — so
    resolving explicitly is the only way to know which would be used."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    pg.execute(text("""
        INSERT INTO user_settings (id, user_id, vision_model, vision_endpoint)
        VALUES (:id, :u, 'some-other-model', 'http://example.invalid:9999')
        ON CONFLICT (user_id) DO UPDATE
        SET vision_model = 'some-other-model',
            vision_endpoint = 'http://example.invalid:9999'
    """), {"id": str(uuid.uuid4()), "u": alice})
    pg.commit()

    capability = photo_analysis.resolve_capability(pg, alice)
    assert capability.endpoint == "http://example.invalid:9999"
    assert capability.model == "some-other-model"
    # And an endpoint nobody probed is not verified.
    assert capability.verified is False


@requires_pg
def test_the_configured_default_is_the_probed_one(pg, two_athletes):
    """The probe result is recorded in code, and this is what pins it to the
    endpoint the config actually resolves to."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    capability = photo_analysis.resolve_capability(pg, alice)
    assert capability.verified is True, (
        f"{capability.endpoint} / {capability.model} is not in "
        f"VERIFIED_VISION — re-run scripts/fitness_vision_probe.py and "
        f"record the result"
    )
    assert "probed" in capability.detail


def test_the_dead_ollama_default_is_not_claimed_as_verified():
    """`routes/vision.py`'s default does not accept connections. Listing it
    as verified would mean every analysis failed with a connection error
    after passing the capability gate."""
    from app.routes.vision import DEFAULT_VISION_ENDPOINT, DEFAULT_VISION_MODEL
    from app.services.fitness.photo_analysis import VERIFIED_VISION

    assert (DEFAULT_VISION_ENDPOINT, DEFAULT_VISION_MODEL) not in VERIFIED_VISION


# ─────────────────────────────────────────────────────────────────────────
# The wire format
# ─────────────────────────────────────────────────────────────────────────

class _CapturingClient:
    """Stands in for httpx.AsyncClient and records the request body."""

    captured: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kwargs):
        type(self).captured.append({"url": url, "body": json})

        class _Response:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {
                    "model": "qwen3.6-35b-a3b",
                    "choices": [{"message": {
                        "content": _observation().model_dump_json(),
                    }}],
                }

        return _Response()


def test_the_request_is_the_shape_the_probe_verified(monkeypatch):
    """§27.1: "do not assume Qwen text lane handles multimodal input". The
    probe verified the OpenAI-compatible `image_url` shape against this
    endpoint, so that is the shape this builds — not the native Ollama
    `{"images": [...]}` body, which the same server would answer by
    ignoring the image.
    """
    import httpx

    from app.prompts import fitness_photo_observations as prompts
    from app.services.fitness import photo_analysis

    _CapturingClient.captured = []
    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)

    capability = photo_analysis.VisionCapability(
        endpoint="http://10.185.1.8:8686", model="qwen3.6-35b-a3b",
        transport="openai", verified=True, detail="probed",
    )
    answer, model = asyncio.run(photo_analysis._chat(
        capability, "system text", "user text", ["AAAA", "BBBB"],
    ))
    assert model == "qwen3.6-35b-a3b"

    sent = _CapturingClient.captured[0]
    assert sent["url"] == "http://10.185.1.8:8686/v1/chat/completions"
    body = sent["body"]
    assert body["model"] == "qwen3.6-35b-a3b"
    assert body["stream"] is False
    # §9: always set max_tokens, or an abandoned request runs the server
    # until the context is full.
    assert body["max_tokens"] == prompts.MAX_OUTPUT_TOKENS
    # §9: nested, where the template actually reads it. Top-level is
    # accepted and ignored, and `content` comes back empty.
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "enable_thinking" not in body

    # Two images, in order, as content parts — not an Ollama `images` list.
    parts = body["messages"][1]["content"]
    assert "images" not in body["messages"][1]
    assert [part["type"] for part in parts] == ["text", "image_url", "image_url"]
    assert parts[1]["image_url"]["url"].endswith("AAAA")
    assert parts[2]["image_url"]["url"].endswith("BBBB")


@requires_pg
def test_only_the_probed_transport_is_ever_selected(pg, two_athletes):
    """The plan asks for both request formats "where configured". One is:
    the OpenAI-compatible transport, which the probe verified. Resolving to
    a native-Ollama transport would mean sending a body shape nothing here
    has ever seen answered."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    assert photo_analysis.resolve_capability(pg, alice).transport == "openai"
    source = open(photo_analysis.__file__).read()
    assert 'transport="ollama"' not in source


def test_a_v1_suffixed_endpoint_is_not_doubled(monkeypatch):
    """`llm_config` values carry `/v1` sometimes and not others, and
    `/v1/v1/chat/completions` is a 404 that reads as an unavailable model."""
    import httpx

    from app.services.fitness import photo_analysis

    _CapturingClient.captured = []
    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)

    capability = photo_analysis.VisionCapability(
        endpoint="http://10.185.1.8:8686/v1/", model="m",
        transport="openai", verified=True, detail="probed",
    )
    asyncio.run(photo_analysis._chat(capability, "s", "u", ["AAAA"]))
    assert _CapturingClient.captured[0]["url"] == (
        "http://10.185.1.8:8686/v1/chat/completions"
    )


# ─────────────────────────────────────────────────────────────────────────
# Consent and ownership
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_photo_without_consent_is_refused_before_the_bytes_are_read(
    pg, two_athletes, monkeypatch,
):
    """Reading somebody's photo out of object storage to decide whether we
    are allowed to read it is the wrong way round."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice, consent=False)

    fetched = []
    monkeypatch.setattr(
        photo_analysis, "_fetch_images",
        lambda *a, **k: fetched.append(True) or [],
    )
    with pytest.raises(photo_analysis.AnalysisRefused) as excinfo:
        asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert excinfo.value.category.value == "no_consent"
    assert "not permission" in str(excinfo.value)
    assert fetched == []


@requires_pg
def test_a_pair_needs_consent_on_both_photos(pg, two_athletes, monkeypatch):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    first = _photo(pg, alice, consent=True)
    second = _photo(pg, alice, consent=False)

    monkeypatch.setattr(
        photo_analysis, "_fetch_images", lambda *a, **k: [],
    )
    with pytest.raises(photo_analysis.AnalysisRefused):
        asyncio.run(photo_analysis.analyse_photo(
            pg, alice, first, compare_photo_id=second,
        ))


@requires_pg
def test_one_athlete_cannot_analyse_anothers_photo(pg, two_athletes):
    from app.services.fitness import photo_analysis

    alice, bob = two_athletes
    photo_id = _photo(pg, alice)
    with pytest.raises(LookupError):
        asyncio.run(photo_analysis.analyse_photo(pg, bob, photo_id))


@requires_pg
def test_a_pair_cannot_span_two_athletes(pg, two_athletes):
    """§5: an FK to a UUID alone does not enforce ownership, and a pair
    spanning two people would describe one person's body in the other's
    record."""
    from app.services.fitness import photo_analysis

    alice, bob = two_athletes
    alices = _photo(pg, alice)
    bobs = _photo(pg, bob)

    with pytest.raises(LookupError):
        asyncio.run(photo_analysis.analyse_photo(
            pg, alice, alices, compare_photo_id=bobs,
        ))

    # And the database refuses it even if a path forgot.
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_photo_analysis
                (id, user_id, kind, source_photo_id, compare_photo_id,
                 status, prompt_version)
            VALUES (:id, :u, 'pair', :src, :cmp, 'pending', 'v1')
        """), {
            "id": str(uuid.uuid4()), "u": alice, "src": alices, "cmp": bobs,
        })
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_photo_cannot_be_compared_with_itself(pg, two_athletes):
    """The answer would be "identical" and it would look like a finding."""
    from app.services.fitness import photo_analysis
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    with pytest.raises(FitnessDataError):
        asyncio.run(photo_analysis.analyse_photo(
            pg, alice, photo_id, compare_photo_id=photo_id,
        ))


@requires_pg
def test_a_deleted_photo_cannot_be_analysed(pg, two_athletes):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    pg.execute(text("""
        UPDATE progress_photo SET deleted_at = NOW() WHERE id = :id
    """), {"id": photo_id})
    pg.commit()

    with pytest.raises(LookupError):
        asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))


@requires_pg
def test_the_service_refuses_a_missing_owner(pg, two_athletes):
    from app.services.fitness import photo_analysis
    from app.services.fitness.data_access import FitnessDataError

    for bad in ("", None, "  "):
        with pytest.raises((FitnessDataError, ValueError)):
            asyncio.run(photo_analysis.analyse_photo(pg, bad, "whatever"))


# ─────────────────────────────────────────────────────────────────────────
# A stubbed roundtrip: storage, idempotency, failure handling
# ─────────────────────────────────────────────────────────────────────────

class _VisionStub:
    def __init__(self, *answers, raises=None, model="qwen3.6-35b-a3b"):
        self.answers = list(answers)
        self.raises = raises
        self.model = model
        self.calls = []

    async def __call__(self, capability, system, user_prompt, images):
        self.calls.append({
            "system": system, "prompt": user_prompt, "images": len(images),
            "endpoint": capability.endpoint,
        })
        if self.raises is not None:
            raise self.raises
        answer = self.answers.pop(0) if self.answers else ""
        if isinstance(answer, dict):
            answer = json.dumps(answer)
        return answer, self.model


@pytest.fixture
def stub_vision(monkeypatch):
    from app.services.fitness import photo_analysis

    def install(*answers, **kwargs):
        stub = _VisionStub(*answers, **kwargs)
        monkeypatch.setattr(photo_analysis, "_chat", stub)
        monkeypatch.setattr(
            photo_analysis, "_fetch_images",
            lambda source, compare: ["AAAA"] * (2 if compare else 1),
        )
        return stub

    return install


@requires_pg
def test_a_valid_observation_is_stored(pg, two_athletes, stub_vision):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub = stub_vision(json.loads(_observation().model_dump_json()))

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.status.value == "complete", result.detail
    assert len(stub.calls) == 1
    assert stub.calls[0]["images"] == 1

    row = pg.execute(text("""
        SELECT status, output::text AS body, summary, model_actual,
               vision_verified, prompt_version, output_schema_version
        FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).fetchone()
    assert row.status == "complete"
    assert "Shoulders" in row.summary
    assert row.model_actual == "qwen3.6-35b-a3b"
    assert row.vision_verified is True
    assert row.output_schema_version == 1
    # No image bytes anywhere in the row.
    assert "AAAA" not in row.body


@requires_pg
def test_the_same_photo_and_prompt_is_one_analysis(pg, two_athletes, stub_vision):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub = stub_vision(
        json.loads(_observation().model_dump_json()),
        json.loads(_observation().model_dump_json()),
    )

    first = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    second = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert first.analysis_id == second.analysis_id
    assert second.duplicate is True
    assert len(stub.calls) == 1, "a duplicate request paid for a second call"


@requires_pg
def test_a_replaced_image_is_a_new_analysis(pg, two_athletes, stub_vision):
    """`capture_hash` is in the idempotency key, so changed pixels produce a
    new analysis rather than reusing a description of the old ones."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice, sha="a" * 64)
    stub_vision(
        json.loads(_observation().model_dump_json()),
        json.loads(_observation().model_dump_json()),
    )

    first = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    pg.execute(text("""
        UPDATE progress_photo SET content_sha256 = :sha WHERE id = :id
    """), {"sha": "b" * 64, "id": photo_id})
    pg.commit()
    second = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert second.analysis_id != first.analysis_id


@requires_pg
def test_a_pair_sends_two_images_in_order(pg, two_athletes, stub_vision):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    earlier = _photo(pg, alice)
    later = _photo(pg, alice)
    stub = stub_vision(json.loads(_comparison().model_dump_json()))

    result = asyncio.run(photo_analysis.analyse_photo(
        pg, alice, earlier, compare_photo_id=later,
    ))
    assert result.status.value == "complete"
    assert stub.calls[0]["images"] == 2
    assert "FIRST image is the earlier photo" in stub.calls[0]["system"]


@requires_pg
def test_an_inconclusive_comparison_is_terminal_not_failed(
    pg, two_athletes, stub_vision,
):
    """"These two cannot be compared" is frequently the only honest reading.
    Calling it failed would invite a retry that cannot help."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    earlier = _photo(pg, alice)
    later = _photo(pg, alice)
    stub_vision(json.loads(_comparison(
        verdict="inconclusive", capture_consistent=False,
        inconclusive_reason="the lighting differs between the two",
    ).model_dump_json()))

    result = asyncio.run(photo_analysis.analyse_photo(
        pg, alice, earlier, compare_photo_id=later,
    ))
    assert result.status.value == "inconclusive"
    row = pg.execute(text("""
        SELECT status, failure_category, output IS NOT NULL AS has_output
        FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).fetchone()
    assert row.status == "inconclusive"
    assert row.failure_category is None
    assert row.has_output is True


@requires_pg
def test_a_composition_claim_fails_the_analysis_after_one_repair(
    pg, two_athletes, stub_vision,
):
    """One repair turn, then refused. The output is never stored."""
    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    bad = json.loads(_observation().model_dump_json())
    bad["summary"] = "Looks about 14% body fat."
    stub = stub_vision(bad, bad)

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert len(stub.calls) == 2, "the repair budget is one turn"
    assert result.status.value == "failed"
    assert result.failure_category is PhotoAnalysisFailure.BODY_COMPOSITION_CLAIM
    row = pg.execute(text("""
        SELECT output, summary FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).fetchone()
    assert row.output is None
    assert row.summary is None
    # And the rejected text is not kept in the failure detail either.
    detail = pg.execute(text("""
        SELECT failure_detail FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).scalar()
    assert "14%" not in (detail or "")


@requires_pg
def test_a_repaired_output_is_accepted(pg, two_athletes, stub_vision):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    bad = json.loads(_observation().model_dump_json())
    bad["summary"] = "Around 14% body fat."
    stub = stub_vision(bad, json.loads(_observation().model_dump_json()))

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert len(stub.calls) == 2
    assert result.status.value == "complete"


@requires_pg
def test_prose_instead_of_json_fails_with_a_category(
    pg, two_athletes, stub_vision,
):
    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub_vision("Here is my assessment of the photo…", "still prose")

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.failure_category is PhotoAnalysisFailure.INVALID_OUTPUT


@requires_pg
def test_a_timeout_is_categorised_as_a_timeout(pg, two_athletes, stub_vision):
    import httpx

    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub_vision(raises=httpx.ReadTimeout("too slow"))

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.failure_category is PhotoAnalysisFailure.MODEL_TIMEOUT


@requires_pg
def test_an_unreachable_endpoint_does_not_fall_back_to_a_cloud_model(
    pg, two_athletes, stub_vision,
):
    """§27.5: default no cloud fallback. An unavailable local endpoint is a
    failed analysis, not a reason to send somebody's body to an API."""
    import httpx

    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub_vision(raises=httpx.ConnectError("her is down"))

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.failure_category is PhotoAnalysisFailure.MODEL_UNAVAILABLE

    source = open(photo_analysis.__file__).read()
    for cloud in ("api.openai.com", "api.anthropic.com", "openai.ChatCompletion",
                  "ANTHROPIC_API_KEY"):
        assert cloud not in source, cloud


@requires_pg
def test_a_source_deleted_mid_run_does_not_leave_a_stale_result(
    pg, two_athletes, monkeypatch,
):
    """A description of pixels nobody can see is worse than no description:
    it would be shown beside a photo that is gone."""
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)

    async def delete_then_answer(capability, system, prompt, images):
        pg.execute(text("""
            UPDATE progress_photo SET deleted_at = NOW() WHERE id = :id
        """), {"id": photo_id})
        pg.commit()
        return _observation().model_dump_json(), "qwen3.6-35b-a3b"

    monkeypatch.setattr(photo_analysis, "_chat", delete_then_answer)
    monkeypatch.setattr(
        photo_analysis, "_fetch_images", lambda source, compare: ["AAAA"],
    )

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.status.value == "source_gone"
    row = pg.execute(text("""
        SELECT status, output, failure_category
        FROM fitness_photo_analysis WHERE id = :id
    """), {"id": result.analysis_id}).fetchone()
    assert row.output is None
    assert row.failure_category == "source_changed"


@requires_pg
def test_unreadable_bytes_fail_without_calling_the_model(
    pg, two_athletes, monkeypatch,
):
    from app.schemas.fitness_coach import PhotoAnalysisFailure
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)

    def explode(source, compare):
        raise RuntimeError("minio is down")

    called = []
    async def should_not_run(*a, **k):
        called.append(True)
        return "", None

    monkeypatch.setattr(photo_analysis, "_fetch_images", explode)
    monkeypatch.setattr(photo_analysis, "_chat", should_not_run)

    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))
    assert result.failure_category is PhotoAnalysisFailure.IMAGE_UNREADABLE
    assert called == []


# ─────────────────────────────────────────────────────────────────────────
# Audit: immutable, and holding nothing it should not
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_terminal_analysis_is_immutable(pg, two_athletes, stub_vision):
    from app.services.fitness import photo_analysis

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub_vision(json.loads(_observation().model_dump_json()))
    result = asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))

    for column, value in (
        ("output", "'{\"summary\": \"rewritten\"}'::jsonb"),
        ("summary", "'rewritten'"),
        ("model_actual", "'a-different-model'"),
        ("capture_hash", "'deadbeef'"),
    ):
        with pytest.raises((IntegrityError, DBAPIError)):
            pg.execute(text(
                f"UPDATE fitness_photo_analysis SET {column} = {value} "
                f"WHERE id = :id"
            ), {"id": result.analysis_id})
            pg.commit()
        pg.rollback()


@requires_pg
def test_the_table_holds_no_image_bytes_or_reasoning(pg):
    """§27: no bytes and no hidden chain-of-thought. A photo copy here would
    be a second place to leak it from, and a stored reasoning chain is
    private musing about somebody's body kept for no reader."""
    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_photo_analysis'
    """)).fetchall()}
    for forbidden in ("image", "image_bytes", "photo_bytes", "thumbnail",
                      "reasoning", "reasoning_content", "raw_output",
                      "transcript", "prompt_text", "body_fat",
                      "body_fat_percent", "lean_mass", "bmi"):
        assert forbidden not in columns, forbidden


def test_the_module_never_salvages_a_reasoning_chain():
    """`routes/vision.py` falls back to `reasoning_content` when `content`
    is empty, which is right for a screenshot and wrong here: salvaging it
    would store a chain-of-thought about somebody's body."""
    from app.services.fitness import photo_analysis

    source = open(photo_analysis.__file__).read()
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    assert 'message.get("reasoning_content")' not in code


@requires_pg
def test_a_completed_analysis_requires_output_at_the_database_level(
    pg, two_athletes,
):
    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_photo_analysis
                (id, user_id, kind, source_photo_id, status, prompt_version)
            VALUES (:id, :u, 'single', :src, 'complete', 'v1')
        """), {"id": str(uuid.uuid4()), "u": alice, "src": photo_id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_pair_row_without_a_second_photo_is_refused(pg, two_athletes):
    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_photo_analysis
                (id, user_id, kind, source_photo_id, status, prompt_version)
            VALUES (:id, :u, 'pair', :src, 'pending', 'v1')
        """), {"id": str(uuid.uuid4()), "u": alice, "src": photo_id})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# The state summarises validated observations only
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_state_summarises_validated_observations_only(
    pg, two_athletes, stub_vision,
):
    """§27.4. A failed analysis contributes nothing, and the legacy
    free-text critique is excluded entirely — it was written by a prompt
    that asked for a body-fat estimate."""
    from app.schemas.fitness_coach import StateSection
    from app.services.fitness import photo_analysis
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    good = _photo(pg, alice)
    bad = _photo(pg, alice)

    stub_vision(
        json.loads(_observation().model_dump_json()),
        "prose", "still prose",
    )
    asyncio.run(photo_analysis.analyse_photo(pg, alice, good))
    asyncio.run(photo_analysis.analyse_photo(pg, alice, bad))

    # A legacy critique on a third photo, which must not appear.
    legacy = _photo(pg, alice)
    pg.execute(text("""
        UPDATE progress_photo
        SET critique = 'Estimated body fat around 14%.',
            critique_model = 'old-vlm', critiqued_at = NOW()
        WHERE id = :id
    """), {"id": legacy})
    pg.commit()

    state = build_fitness_state(
        pg, alice, sections=[StateSection.PHOTOS], fresh=True,
        redis_client=None,
    )
    group = state.sections[StateSection.PHOTOS]
    assert len(group.items) == 1
    assert "Shoulders" in group.items[0]["summary"]
    rendered = json.dumps(group.model_dump(mode="json"))
    assert "body fat" not in rendered.lower()
    assert "14%" not in rendered
    assert any("not measurements" in note for note in group.limitations)


@requires_pg
def test_the_photo_section_carries_no_photo_id_or_bytes(
    pg, two_athletes, stub_vision,
):
    """The state is read into prompts and rendered on screens. A photo id
    here would be the first step toward one of them fetching it."""
    from app.schemas.fitness_coach import StateSection
    from app.services.fitness import photo_analysis
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    photo_id = _photo(pg, alice)
    stub_vision(json.loads(_observation().model_dump_json()))
    asyncio.run(photo_analysis.analyse_photo(pg, alice, photo_id))

    state = build_fitness_state(
        pg, alice, sections=[StateSection.PHOTOS], fresh=True,
        redis_client=None,
    )
    rendered = json.dumps(
        state.sections[StateSection.PHOTOS].model_dump(mode="json")
    )
    assert photo_id not in rendered
    assert "storage_key" not in rendered
    assert "key-" not in rendered


def test_a_weekly_review_does_not_read_photo_observations():
    """A review's job is the numbers. Folding in a photo description would
    let it cite "looks leaner" as evidence for a calorie change, which is
    the composition claim the photo schema spends itself preventing."""
    from app.schemas.fitness_coach import StateSection
    from app.services.fitness.reviews import REVIEW_SECTIONS

    assert StateSection.PHOTOS not in REVIEW_SECTIONS


# ─────────────────────────────────────────────────────────────────────────
# The real roundtrip
# ─────────────────────────────────────────────────────────────────────────

def _probe_reachable() -> bool:
    import socket
    try:
        from app.core.llm_config import llm_config
        url = str(llm_config.vision_url)
        host = url.split("//", 1)[-1].split("/")[0]
        hostname, _, port = host.partition(":")
        with socket.create_connection((hostname, int(port or 80)), timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _probe_reachable(),
    reason=(
        "the vision endpoint is unreachable from here. The disposable stack "
        "is network-isolated by design; run this with host networking: "
        "docker run --rm --network host -v $PWD/backend:/app:ro -w /app "
        "jarvis-backend:latest python -m pytest "
        "tests/test_fitness_photo_analysis.py -k real_vision"
    ),
)
def test_real_vision_sees_a_synthetic_image():
    """The gate: an actual roundtrip, because mock-only tests cannot prove
    deployed capability.

    A SYNTHETIC image — a coloured shape drawn in-process. No athlete's
    photo goes near a test. If the model names the shape and the colour, the
    image reached it; if it does not, nothing about the physique prompt is
    worth trying.
    """
    from app.routes.vision import call_openai_vision
    from app.core.llm_config import llm_config
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (512, 512), (255, 255, 255))
    ImageDraw.Draw(canvas).ellipse((96, 96, 416, 416), fill=(220, 30, 30))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()

    result = asyncio.run(call_openai_vision(
        encoded,
        "Answer with two words only: the colour and the shape you can see. "
        "If you cannot see an image, answer exactly: NO IMAGE.",
        str(llm_config.vision_model), str(llm_config.vision_url),
        max_tokens=40,
    ))
    answer = (result.get("response") or "").lower()
    assert "no image" not in answer, (
        "the endpoint answered the text prompt without the image — it is "
        "serving this model without --mmproj"
    )
    assert "red" in answer or "crimson" in answer, answer
    assert "circle" in answer or "round" in answer, answer
