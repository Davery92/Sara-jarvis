"""Step 20 of FITNESS_COACH_IMPLEMENTATION_PLAN: the review flow end to end,
against a real database, with the model stubbed.

The three completion criteria, each a section below:

* **Inspectable and explains its limits.** A complete review stores what it
  reasoned from and says what it could not tell.
* **Validation is enforceable beyond prompt instructions.** An ungrounded
  output is a stored `failed` review with a category — not text that reached
  David.
* **No plan or target changes occur during review generation.** Asserted by
  counting rows before and after, because the whole point of "a review is a
  proposal" is that generating one writes nothing.

Plus the operational properties: a provider outage leaves the deterministic
state intact, duplicate workers produce one artifact, an insufficient week is
its own terminal state, and no transaction is held across the model call.

The model is stubbed here on purpose. §20's gate also requires one real
isolated local-model smoke test, which cannot run in a disposable stack with
no GPU host — `scripts/fitness_coach_smoke.py` is that test, and its
invocation is recorded in the release verification doc.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_reviews_pg.py
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
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


@pytest.fixture(autouse=True)
def review_flag_on(monkeypatch):
    """The generator's flag is off by default. These tests are about the
    generator, so they turn it on — and one test turns it back off to prove
    the gate works."""
    from app.core import feature_flags

    monkeypatch.setattr(
        feature_flags, "is_enabled",
        lambda flag: feature_flags._flag_name(flag) == "FITNESS_COACH_REVIEW",
    )


@pytest.fixture
def two_athletes(pg):
    unusable_hash = "$2b$12$" + "x" * 53
    alice = f"s20a-{uuid.uuid4().hex[:17]}"
    bob = f"s20b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s20.invalid", "p": unusable_hash})
        pg.execute(text("""
            INSERT INTO fitness_athlete_profile
                (id, user_id, timezone, created_at, updated_at)
            VALUES (:i, :u, 'America/New_York', NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
        """), {"i": str(uuid.uuid4()), "u": uid})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_coach_recommendation", "fitness_coach_review",
                  "fitness_target_revision", "fitness_athlete_goal",
                  "fitness_athlete_profile", "health_metric", "food_log",
                  "daily_recovery_log", "weight_trend", "workout_log",
                  "workout", "fitness_phase", "fitness_program",
                  "fitness_goals", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _today(pg, user_id) -> date:
    from app.services.fitness.profile import athlete_today
    return athlete_today(pg, user_id)


def _weigh_in(pg, user_id, day: date, kg: float):
    from app.schemas.fitness_coach import Unit
    from app.services.fitness.observations import ingest_observation
    ingest_observation(
        pg, user_id, metric_type="weight", value=kg, unit=Unit.KG,
        recorded_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=ET),
        source="manual", timezone_name="America/New_York",
    )
    pg.commit()


def _meal(pg, user_id, day: date, calories=3000, protein=200):
    pg.execute(text("""
        INSERT INTO food_log
            (id, user_id, meal_type, food_items, calories, protein,
             logged_at, created_at, updated_at)
        VALUES (:id, :u, 'dinner', CAST(:fi AS jsonb), :cal, :pro,
                :logged, NOW(), NOW())
    """), {
        "id": str(uuid.uuid4()), "u": user_id,
        "fi": json.dumps([{"name": "chicken", "quantity": 1, "unit": "serving"}]),
        "cal": calories, "pro": protein,
        "logged": datetime(day.year, day.month, day.day, 18, 0),
    })
    pg.execute(text("""
        INSERT INTO daily_recovery_log
            (id, user_id, log_date, nutrition_status, nutrition_completed_at,
             sleep_hours, created_at, updated_at)
        VALUES (:i, :u, :d, 'complete', NOW(), 7.5, NOW(), NOW())
        ON CONFLICT (user_id, log_date) DO UPDATE
        SET nutrition_status = 'complete', nutrition_completed_at = NOW(),
            sleep_hours = 7.5
    """), {"i": str(uuid.uuid4()), "u": user_id, "d": day})
    pg.commit()


def _a_good_week(pg, user_id, *, days: int = 15):
    """Fifteen days, not seven.

    A weekly velocity compares this week's mean to the PREVIOUS week's, so a
    single week leaves `weight.velocity_weekly` unavailable — and a
    recommendation that cites only unavailable metrics is correctly rejected
    by the safety gate. Seeding one week made these tests exercise the
    rejection path instead of the path they were written for.
    """
    today = _today(pg, user_id)
    for offset in range(1, days + 1):
        day = today - timedelta(days=offset)
        _weigh_in(pg, user_id, day, 81.0 + offset * 0.08)
        _meal(pg, user_id, day)
    return today


def _model_output(**overrides) -> dict:
    body = {
        "output_version": 1,
        "summary": "Weight drifted down across 7 of 7 logged days.",
        "coaching_priority": "Keep the weigh-ins and the food log going.",
        "observations": [{
            "text": "Weekly change was negative over 7 of 7 days.",
            "metric_paths": ["weight.velocity_weekly"],
        }],
        "limitations": ["Only one week of data; no longer trend yet."],
        "confidence": "moderate",
        "confidence_basis": "seven of seven days have a weigh-in",
        "recommendations": [{
            "category": "maintain",
            "headline": "Hold the current targets",
            "rationale": "The rate is on plan over 7 of 7 logged days.",
            "metric_paths": ["weight.velocity_weekly"],
            "evidence_refs": [],
            "confidence": "moderate",
            "confidence_basis": "seven of seven days observed",
            "proposed_change": {"kind": "none"},
        }],
    }
    body.update(overrides)
    return body


class StubModel:
    """A stand-in for the local background client.

    Records every call, so "exactly one call" and "one repair at most" are
    assertable — the repair budget is a real cost in GPU time and the
    athlete's wait, not a style preference.
    """

    def __init__(self, *responses, raises=None, model="qwen3.8-27b"):
        self.responses = list(responses)
        self.raises = raises
        self.model = model
        self.calls = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.raises is not None:
            raise self.raises
        body = self.responses.pop(0) if self.responses else ""
        if isinstance(body, dict):
            body = json.dumps(body)
        return {
            "model": self.model,
            "choices": [{"message": {"content": body}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
        }


@pytest.fixture
def stub_model(monkeypatch):
    holder = {}

    def install(*responses, **kwargs):
        stub = StubModel(*responses, **kwargs)
        import app.core.llm as llm_module
        monkeypatch.setattr(llm_module, "get_background_llm_client", lambda: stub)
        holder["stub"] = stub
        return stub

    return install


def _request(pg, user_id, **kwargs):
    from app.services.fitness import reviews
    review = reviews.request_review(pg, user_id, **kwargs)
    pg.commit()
    return review


def _generate(pg, user_id, review_id):
    from app.services.fitness import reviews
    return asyncio.run(reviews.generate(pg, user_id, review_id))


# ─────────────────────────────────────────────────────────────────────────
# A complete review is inspectable and states its limits
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_complete_review_stores_what_it_reasoned_from(pg, two_athletes, stub_model):
    from app.schemas.fitness_coach import ReviewStatus
    from app.services.fitness.review_audit import get_review

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output())

    review = _request(pg, alice)
    assert review.status is ReviewStatus.PENDING

    result = _generate(pg, alice, review.id)
    assert result.review.status is ReviewStatus.COMPLETE, result.notes

    detail = get_review(pg, alice, review.id, with_state=True)
    assert detail.input_state is not None
    assert "weight.velocity_weekly" in detail.input_state.metric_paths()
    assert detail.input_state.sections["weight"].metrics["velocity_weekly"].value \
        is not None, "the fixture must give the review a usable velocity"
    assert detail.output is not None
    assert detail.output.limitations
    assert detail.model_actual == "qwen3.8-27b"
    assert detail.prompt_version == "fitness_coach_review_v1"
    assert detail.prompt_hash and len(detail.prompt_hash) == 64
    assert len(stub.calls) == 1


@requires_pg
def test_the_review_states_its_limits(pg, two_athletes, stub_model):
    """"On-demand Weekly Review is inspectable and explains its limits."" A
    review with no limitations section would read as a complete picture."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model(_model_output())
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.output.limitations


@requires_pg
def test_the_model_call_is_bounded_and_thinking_is_off(pg, two_athletes, stub_model):
    """Qwen returns an empty `content` for structured output unless
    `enable_thinking` is False, nested in `chat_template_kwargs`. And every
    background call carries a token cap: `llama-server` keeps generating
    after a non-streaming client disconnects."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output())
    review = _request(pg, alice)
    _generate(pg, alice, review.id)

    kwargs = stub.calls[0]["kwargs"]
    assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert kwargs["max_tokens"] and kwargs["max_tokens"] <= 4096
    assert kwargs["request_timeout"] and kwargs["request_timeout"] <= 300
    # Pinned to the bg lane: the fast tier's 16k slots cannot hold a month of
    # state, and a silent truncation there would make the model reason from a
    # partial state while the stored snapshot shows the whole one.
    assert kwargs["tier"] == "bg"


@requires_pg
def test_the_prompt_never_carries_the_owner_id(pg, two_athletes, stub_model):
    """The model has no use for it and it is the one field that identifies
    whose body this is."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output())
    review = _request(pg, alice)
    _generate(pg, alice, review.id)

    sent = json.dumps(stub.calls[0]["messages"])
    assert alice not in sent


# ─────────────────────────────────────────────────────────────────────────
# Generation writes no plan or target
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_review_generation_makes_zero_target_or_program_mutations(
    pg, two_athletes, stub_model,
):
    """The completion criterion, asserted by counting.

    The whole point of "a review is a proposal" is that generating one
    changes nothing an athlete is following.
    """
    alice, _ = two_athletes
    _a_good_week(pg, alice)

    def counts():
        return {
            table: pg.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = :u"
            ), {"u": alice}).scalar()
            for table in ("fitness_target_revision", "fitness_phase",
                          "fitness_program", "fitness_goals", "workout_log")
        }

    before = counts()
    stub_model(_model_output(recommendations=[{
        "category": "nutrition_change",
        "headline": "Drop calories by 150",
        "rationale": "Weight is flat against a cut over 7 of 7 logged days.",
        "metric_paths": ["weight.velocity_weekly"],
        "evidence_refs": [],
        "confidence": "moderate",
        "confidence_basis": "seven of seven days",
        "proposed_change": {
            "kind": "target_revision", "scope": "default",
            "effective_date": (_today(pg, alice) + timedelta(days=1)).isoformat(),
            "target_values": {"calories": 2850, "protein_g": 200},
        },
    }]))
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)

    assert counts() == before, "review generation mutated a plan or target"
    # And the proposal IS stored, as a proposal.
    assert len(result.recommendations) == 1
    assert result.recommendations[0].decision_status.value == "proposed"
    assert result.recommendations[0].applied_revision_id is None


@requires_pg
def test_a_stored_proposal_records_the_revision_it_was_measured_against(
    pg, two_athletes, stub_model,
):
    """A proposal written against a target the athlete has since changed is
    stale, and without this it would be silently applied over the newer
    value."""
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    today = _a_good_week(pg, alice)
    baseline = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=today - timedelta(days=30),
        training=TargetValues(calories=3000, protein_g=200),
    ))
    pg.commit()

    stub_model(_model_output())
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.recommendations[0].current_target_revision_id == baseline.id


# ─────────────────────────────────────────────────────────────────────────
# Validation is enforced
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_invented_metric_is_repaired_once_then_rejected(
    pg, two_athletes, stub_model,
):
    """One repair turn, not a loop. A model that cannot produce the schema
    twice will not produce it on the fifth attempt, and each attempt costs a
    wait and a GPU slot."""
    from app.schemas.fitness_coach import ReviewFailureCategory, ReviewStatus

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    bad = _model_output(observations=[{
        "text": "Your body fat is down 1.2%.",
        "metric_paths": ["body_composition.fat_percent"],
    }])
    stub = stub_model(bad, bad)

    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)

    assert len(stub.calls) == 2, "the repair budget is one turn"
    assert result.review.status is ReviewStatus.FAILED
    assert result.review.error_category is ReviewFailureCategory.UNGROUNDED_CLAIM


@requires_pg
def test_a_repaired_output_is_accepted(pg, two_athletes, stub_model):
    from app.schemas.fitness_coach import ReviewStatus

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    bad = _model_output(observations=[{
        "text": "Your body fat is down.",
        "metric_paths": ["body_composition.fat_percent"],
    }])
    stub = stub_model(bad, _model_output())

    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert len(stub.calls) == 2
    assert result.review.status is ReviewStatus.COMPLETE


@requires_pg
def test_a_diagnosis_fails_the_review_without_a_repair_attempt(
    pg, two_athletes, stub_model,
):
    """A sentence containing a diagnosis cannot be repaired by deleting a
    word — the reasoning behind it assumed the diagnosis, and shipping the
    rest would leave advice built on a clinical claim with the claim edited
    out."""
    from app.schemas.fitness_coach import ReviewFailureCategory, ReviewStatus

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output(
        summary="This looks like tendinitis in the right elbow.",
    ))

    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)

    assert len(stub.calls) == 1, "a safety rejection is not repairable"
    assert result.review.status is ReviewStatus.FAILED
    assert result.review.error_category is ReviewFailureCategory.SAFETY_REFUSED


@requires_pg
def test_malformed_output_fails_with_a_category_and_no_summary(
    pg, two_athletes, stub_model,
):
    from app.schemas.fitness_coach import ReviewFailureCategory, ReviewStatus

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model("I'd love to help but here is some prose instead.",
               "still prose")

    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.review.status is ReviewStatus.FAILED
    assert result.review.error_category is ReviewFailureCategory.INVALID_OUTPUT
    assert result.review.summary is None


@requires_pg
def test_an_out_of_bounds_target_fails_the_review(pg, two_athletes, stub_model):
    alice, _ = two_athletes
    today = _a_good_week(pg, alice)
    stub_model(_model_output(recommendations=[{
        "category": "nutrition_change",
        "headline": "Cut hard",
        "rationale": "Weight is flat over 7 of 7 logged days.",
        "metric_paths": ["weight.velocity_weekly"],
        "evidence_refs": [],
        "confidence": "moderate",
        "confidence_basis": "seven of seven days",
        "proposed_change": {
            "kind": "target_revision", "scope": "default",
            "effective_date": (today + timedelta(days=1)).isoformat(),
            "target_values": {"calories": 900, "protein_g": 200},
        },
    }]))
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.review.status.value == "failed"
    assert any("under any circumstances" in n for n in result.notes)


@requires_pg
def test_a_failed_review_stores_no_prompt_or_transcript(
    pg, two_athletes, stub_model,
):
    """A failed review that banked the full prompt would make this table the
    largest copy of the athlete's private data, kept for the least useful
    reason."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model("prose", "more prose")
    review = _request(pg, alice)
    _generate(pg, alice, review.id)

    row = pg.execute(text("""
        SELECT error_detail, output FROM fitness_coach_review WHERE id = :id
    """), {"id": review.id}).fetchone()
    assert row.output is None
    assert row.error_detail and len(row.error_detail) <= 500
    assert "ALLOWED_METRIC_PATHS" not in (row.error_detail or "")


# ─────────────────────────────────────────────────────────────────────────
# Insufficient data
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_nearly_empty_week_is_insufficient_and_never_calls_the_model(
    pg, two_athletes, stub_model,
):
    """Coverage is checked BEFORE the model. A review from two data points
    produces confident text about noise, and the right answer is to say what
    would help — not to spend a call producing something to be ignored."""
    from app.schemas.fitness_coach import ReviewStatus

    alice, _ = two_athletes
    _weigh_in(pg, alice, _today(pg, alice) - timedelta(days=2), 81.0)
    stub = stub_model(_model_output())

    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)

    assert result.review.status is ReviewStatus.INSUFFICIENT_DATA
    assert stub.calls == [], "the model was called for a week with no data"
    assert result.notes and "wanted:" in result.notes[-1]


@requires_pg
def test_insufficient_data_is_not_a_failure(pg, two_athletes, stub_model):
    """The answer to it is to log more, not to retry the model. Folding it
    into `failed` makes a retry loop chase something no retry can fix."""
    from app.schemas.fitness_coach import ReviewStatus

    alice, _ = two_athletes
    stub_model(_model_output())
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.review.status is not ReviewStatus.FAILED
    assert result.review.status is ReviewStatus.INSUFFICIENT_DATA
    assert result.review.error_category.value == "insufficient_data"


# ─────────────────────────────────────────────────────────────────────────
# Outages
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_provider_outage_preserves_the_deterministic_state(
    pg, two_athletes, stub_model,
):
    """§20.6: LLM/network errors preserve deterministic state. The weigh-ins
    and the frozen snapshot are still exactly as they were."""
    import httpx
    from app.schemas.fitness_coach import ReviewFailureCategory

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model(raises=httpx.ConnectError("mac studio is asleep"))

    review = _request(pg, alice)
    before = pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :u
    """), {"u": alice}).scalar()

    result = _generate(pg, alice, review.id)
    assert result.review.status.value == "failed"
    assert result.review.error_category is ReviewFailureCategory.MODEL_UNAVAILABLE

    assert pg.execute(text("""
        SELECT COUNT(*) FROM health_metric WHERE user_id = :u
    """), {"u": alice}).scalar() == before
    # And the snapshot the review opened with is intact.
    from app.services.fitness.review_audit import get_review
    detail = get_review(pg, alice, review.id, with_state=True)
    assert detail.input_state is not None


@requires_pg
def test_a_timeout_is_categorised_as_a_timeout(pg, two_athletes, stub_model):
    """The category drives the retry decision: a timeout is worth retrying
    and an invalid output is not."""
    import httpx
    from app.schemas.fitness_coach import ReviewFailureCategory

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model(raises=httpx.ReadTimeout("too slow"))
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.review.error_category is ReviewFailureCategory.MODEL_TIMEOUT


@requires_pg
def test_an_empty_model_response_is_an_outage_not_an_invalid_output(
    pg, two_athletes, stub_model,
):
    """Qwen returns empty `content` when thinking is on. That is a transport
    misconfiguration, which is worth retrying; a schema violation is not."""
    from app.schemas.fitness_coach import ReviewFailureCategory

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model("")
    review = _request(pg, alice)
    result = _generate(pg, alice, review.id)
    assert result.review.error_category is ReviewFailureCategory.MODEL_UNAVAILABLE


@requires_pg
def test_no_transaction_is_held_across_the_model_call(
    pg, two_athletes, stub_model, monkeypatch,
):
    """Holding one means a slow Mac Studio pins a database connection for the
    length of a generation. The fitness lane and the chat lane share that
    pool, so a stuck review would degrade chat — the thing David is using."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)

    observed = {}

    class Watching(StubModel):
        async def chat_completion(self, messages, **kwargs):
            observed["in_transaction"] = pg.in_transaction()
            return await super().chat_completion(messages, **kwargs)

    stub = Watching(_model_output())
    import app.core.llm as llm_module
    monkeypatch.setattr(llm_module, "get_background_llm_client", lambda: stub)

    review = _request(pg, alice)
    _generate(pg, alice, review.id)
    assert observed["in_transaction"] is False


# ─────────────────────────────────────────────────────────────────────────
# Duplicates, isolation and the flag
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_two_requests_produce_one_review_and_one_model_call(
    pg, two_athletes, stub_model,
):
    """A double-tap on the button must not pay for two generations and
    produce two differently worded answers to one question."""
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output(), _model_output())

    first = _request(pg, alice)
    second = _request(pg, alice)
    assert first.id == second.id

    _generate(pg, alice, first.id)
    _generate(pg, alice, second.id)
    assert len(stub.calls) == 1, "a duplicate worker generated a second answer"


@requires_pg
def test_a_duplicate_worker_returns_the_existing_artifact(
    pg, two_athletes, stub_model,
):
    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model(_model_output())
    review = _request(pg, alice)
    first = _generate(pg, alice, review.id)
    second = _generate(pg, alice, review.id)
    assert second.review.id == first.review.id
    assert second.review.status is first.review.status
    assert "already complete" in " ".join(second.notes)


@requires_pg
def test_requesting_again_after_the_data_changes_needs_force(
    pg, two_athletes, stub_model,
):
    """A rerun costs a model call, so the caller decides to spend it — this
    does not silently supersede."""
    from app.services.fitness.review_audit import ReviewConflict

    alice, _ = two_athletes
    today = _a_good_week(pg, alice)
    stub_model(_model_output(), _model_output())
    first = _request(pg, alice)
    _generate(pg, alice, first.id)

    _weigh_in(pg, alice, today - timedelta(days=3), 79.5)   # a correction

    with pytest.raises(ReviewConflict):
        _request(pg, alice)
    pg.rollback()

    second = _request(pg, alice, force=True)
    assert second.id != first.id
    assert second.supersedes_id == first.id


@requires_pg
def test_one_athlete_cannot_generate_anothers_review(pg, two_athletes, stub_model):
    alice, bob = two_athletes
    _a_good_week(pg, alice)
    stub_model(_model_output())
    review = _request(pg, alice)

    with pytest.raises(LookupError):
        _generate(pg, bob, review.id)


@requires_pg
def test_two_athletes_reviews_do_not_mix(pg, two_athletes, stub_model):
    alice, bob = two_athletes
    _a_good_week(pg, alice)
    _a_good_week(pg, bob)
    stub_model(_model_output(), _model_output())

    a = _request(pg, alice)
    b = _request(pg, bob)
    assert a.id != b.id

    from app.services.fitness.review_audit import list_reviews
    assert [r.id for r in list_reviews(pg, alice)] == [a.id]
    assert [r.id for r in list_reviews(pg, bob)] == [b.id]


@requires_pg
def test_the_flag_gates_the_generator_and_nothing_else(
    pg, two_athletes, stub_model, monkeypatch,
):
    """Flipping it off stops Sara producing new opinions without touching a
    single recorded number, and without hiding reviews she already
    produced."""
    from app.core import feature_flags
    from app.services.fitness import reviews
    from app.services.fitness.state import build_fitness_state

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub = stub_model(_model_output())
    review = _request(pg, alice)

    monkeypatch.setattr(feature_flags, "is_enabled", lambda flag: False)
    with pytest.raises(reviews.ReviewDisabled):
        _generate(pg, alice, review.id)
    assert stub.calls == []

    # The deterministic state still works with the flag off.
    state = build_fitness_state(pg, alice, fresh=True, redis_client=None)
    assert state.sections, "the flag broke the deterministic state"


@requires_pg
def test_the_task_refuses_a_missing_owner():
    """There is no default owner anywhere in this subsystem. A task that
    guessed one would write a review of one athlete's data under another's
    id — which is exactly what Step 2 removed from the HTTP path."""
    from app.tasks.fitness_coach import generate_review_task

    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            generate_review_task.run(user_id=bad, review_id="r-1")


@requires_pg
def test_the_task_module_has_no_default_user_helper():
    """`health_weekly.py` has one; this must not. It picks a user by email
    and falls back to the oldest row, which is the solo-owner stub in a place
    nobody looks."""
    import app.tasks.fitness_coach as module

    assert not hasattr(module, "_default_user_id")
    source = open(module.__file__).read()
    assert "ORDER BY created_at ASC LIMIT 1" not in source


# ─────────────────────────────────────────────────────────────────────────
# The period
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_default_period_is_the_last_seven_complete_days(pg, two_athletes):
    """A review that included this morning would report a calorie figure
    that is simply the morning's."""
    from app.services.fitness.reviews import default_period

    alice, _ = two_athletes
    today = _today(pg, alice)
    period = default_period(pg, alice)
    assert period.end == today            # exclusive
    assert period.start == today - timedelta(days=7)


@requires_pg
def test_an_explicit_period_is_honoured(pg, two_athletes, stub_model):
    from app.schemas.fitness_coach import Period

    alice, _ = two_athletes
    _a_good_week(pg, alice)
    stub_model(_model_output())
    window = Period(start=date(2026, 9, 14), end=date(2026, 9, 21))
    review = _request(pg, alice, period=window)
    assert review.period.start == window.start
    assert review.period.end == window.end


@requires_pg
def test_the_state_includes_the_longer_aggregates(pg, two_athletes, stub_model):
    """§20.1: the prior 7 full days PLUS 14/28-day aggregates. A week in
    isolation cannot tell a trend from a bad week."""
    alice, _ = two_athletes
    today = _today(pg, alice)
    for offset in range(1, 25):
        day = today - timedelta(days=offset)
        _weigh_in(pg, alice, day, 82.0 - offset * 0.05)
        _meal(pg, alice, day)

    stub_model(_model_output())
    review = _request(pg, alice)
    from app.services.fitness.review_audit import get_review
    detail = get_review(pg, alice, review.id, with_state=True)
    weight = detail.input_state.sections["weight"].metrics
    assert "mean_28d" in weight
    assert weight["mean_28d"].value is not None
    # And the weekly figures are still the WEEKLY figures.
    assert weight["mean_7d"].expected_days == 7
