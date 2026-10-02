"""Step 19 of FITNESS_COACH_IMPLEMENTATION_PLAN: the audit trail works
before any model is attached.

The question this storage exists to answer is "why did you tell me to cut
calories?", three months later, when the numbers have moved. That only works
if four things hold, and each is a section below:

1. **A completed review's inputs and output are immutable.** Enforced by a
   database trigger, not a convention — "the snapshot is immutable" kept only
   by code that remembers not to write it is a mutable column with a comment.
2. **Idempotency is a unique index.** Two schedulers on the same due date
   produce one review and one model call, not two differently worded answers
   to one question.
3. **A rerun after corrected data is a linked revision.** The old review was
   a correct reading of the data it had, and it is the only record of why a
   decision was made at the time.
4. **A recommendation cannot masquerade as an applied change.** Claiming
   `accepted` requires the receipt or the revision that proves something
   executed.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_review_audit_pg.py
"""
import json
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
PERIOD_START = date(2026, 9, 21)
PERIOD_END = date(2026, 9, 28)          # exclusive
PROMPT_VERSION = "fitness_coach_review_v1"


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
    alice = f"s19a-{uuid.uuid4().hex[:17]}"
    bob = f"s19b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s19.invalid", "p": unusable_hash})
    pg.commit()
    yield alice, bob
    pg.rollback()
    for table in ("fitness_coach_recommendation", "fitness_coach_review",
                  "fitness_target_revision", "fitness_athlete_profile",
                  "fitness_phase", "fitness_program", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def a_state(user_id: str, *, weight: float = 81.2, span_end: date = PERIOD_END):
    """A minimal but real `FitnessStateV1`."""
    from app.schemas.fitness_coach import (
        FitnessStateV1, Metric, MetricGroup, Period, StateSection, Unit,
    )
    return FitnessStateV1(
        user_id=user_id,
        as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        athlete_local_date=span_end,
        timezone="America/New_York",
        period=Period(start=PERIOD_START, end=span_end),
        data_revision="rev-1",
        sections={
            StateSection.WEIGHT: MetricGroup(
                section=StateSection.WEIGHT,
                metrics={
                    "latest": Metric(
                        key="weight.latest", value=weight, unit=Unit.KG,
                        observed_days=1, expected_days=1,
                    ),
                    "velocity_weekly": Metric(
                        key="weight.velocity_weekly", value=-0.35,
                        unit=Unit.KG_PER_WEEK, observed_days=5, expected_days=7,
                    ),
                },
            ),
        },
    )


def an_output(*, recommendations=None):
    from app.schemas.fitness_coach import (
        ConfidenceCategory, CoachReviewOutputV1, ProposedChange,
        ProposedChangeKind, RecommendationCategory, ReviewObservation,
        ReviewRecommendation, TargetScope, TargetValues,
    )
    if recommendations is None:
        recommendations = [
            ReviewRecommendation(
                category=RecommendationCategory.NUTRITION_CHANGE,
                headline="Drop calories by 100",
                rationale="Weight has been flat for two weeks against a cut target.",
                metric_paths=["weight.velocity_weekly"],
                confidence=ConfidenceCategory.MODERATE,
                confidence_basis="five of seven days have a weigh-in",
                proposed_change=ProposedChange(
                    kind=ProposedChangeKind.TARGET_REVISION,
                    scope=TargetScope.DEFAULT,
                    effective_date=date(2026, 9, 29),
                    target_values=TargetValues(calories=2900, protein_g=200),
                ),
            ),
        ]
    return CoachReviewOutputV1(
        summary="Flat week against a cut target.",
        coaching_priority="Keep weighing in daily.",
        observations=[ReviewObservation(
            text="Weekly change was -0.35 kg/week.",
            metric_paths=["weight.velocity_weekly"],
        )],
        limitations=["Only five of seven days have a weigh-in."],
        confidence=ConfidenceCategory.MODERATE,
        confidence_basis="five of seven days have a weigh-in",
        recommendations=recommendations,
    )


def _open(pg, user_id, *, state=None, **kwargs):
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.review_audit import open_review
    review = open_review(
        pg, user_id, kind=kwargs.pop("kind", ReviewKind.WEEKLY),
        state=state or a_state(user_id),
        prompt_version=kwargs.pop("prompt_version", PROMPT_VERSION),
        **kwargs,
    )
    pg.commit()
    return review


# ─────────────────────────────────────────────────────────────────────────
# 1. Immutability
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_completed_reviews_input_snapshot_cannot_be_changed(pg, two_athletes):
    """A trigger, not a convention.

    "The snapshot is immutable" enforced only by code that remembers not to
    write it is a mutable column with a comment, and the first bulk UPDATE
    proves it.
    """
    from app.services.fitness.review_audit import mark_complete, mark_running

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id, model_actual="qwen3.8-27b")
    mark_complete(pg, alice, review.id, output=an_output())
    pg.commit()

    with pytest.raises((DBAPIError, IntegrityError)) as excinfo:
        pg.execute(text("""
            UPDATE fitness_coach_review
            SET input_state = '{"tampered": true}'::jsonb
            WHERE id = :id
        """), {"id": review.id})
        pg.commit()
    assert "immutable" in str(excinfo.value).lower()
    pg.rollback()

    stored = pg.execute(text("""
        SELECT input_state::text AS body FROM fitness_coach_review WHERE id = :id
    """), {"id": review.id}).fetchone()
    assert "tampered" not in stored.body


@requires_pg
def test_a_completed_reviews_output_and_versions_are_frozen(pg, two_athletes):
    from app.services.fitness.review_audit import mark_complete, mark_running

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    mark_complete(pg, alice, review.id, output=an_output())
    pg.commit()

    for column, value in (
        ("output", "'{\"summary\": \"rewritten\"}'::jsonb"),
        ("analytics_version", "99"),
        ("input_hash", "'deadbeef'"),
        ("period_end", "'2026-10-05'::date"),
        ("model_actual", "'some-other-model'"),
        ("prompt_version", "'v2'"),
    ):
        with pytest.raises((DBAPIError, IntegrityError)):
            pg.execute(text(
                f"UPDATE fitness_coach_review SET {column} = {value} WHERE id = :id"
            ), {"id": review.id})
            pg.commit()
        pg.rollback()


@requires_pg
def test_a_pending_review_is_still_editable(pg, two_athletes):
    """The freeze applies to terminal rows only. A run in progress has to be
    able to record which model actually answered."""
    from app.services.fitness.review_audit import mark_running

    alice, _ = two_athletes
    review = _open(pg, alice)
    updated = mark_running(pg, alice, review.id, model_actual="qwen3.8-27b")
    pg.commit()
    assert updated.model_actual == "qwen3.8-27b"


@requires_pg
def test_superseding_a_terminal_review_is_the_one_permitted_write(pg, two_athletes):
    """`superseded_by_id` may change on a frozen row — it does not alter what
    that review said or reasoned from, and without it the chain could not be
    linked."""
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, supersede,
    )

    alice, _ = two_athletes
    first = _open(pg, alice)
    mark_running(pg, alice, first.id)
    mark_complete(pg, alice, first.id, output=an_output())
    pg.commit()

    second = supersede(
        pg, alice, first.id, state=a_state(alice, weight=80.9),
        prompt_version=PROMPT_VERSION, kind=ReviewKind.WEEKLY,
    )
    pg.commit()

    assert second.supersedes_id == first.id
    assert second.revision == 2
    linked = pg.execute(text(
        "SELECT superseded_by_id FROM fitness_coach_review WHERE id = :id"
    ), {"id": first.id}).scalar()
    assert linked == second.id


# ─────────────────────────────────────────────────────────────────────────
# 2. Idempotency
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_same_question_over_the_same_data_is_one_review(pg, two_athletes):
    """A retry after a timeout must return the existing run.

    Otherwise the athlete pays for a second model call and gets a second,
    differently worded answer to one question.
    """
    alice, _ = two_athletes
    first = _open(pg, alice)
    second = _open(pg, alice)
    assert first.id == second.id

    count = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coach_review WHERE user_id = :uid
    """), {"uid": alice}).scalar()
    assert count == 1


@requires_pg
def test_idempotency_is_enforced_by_the_database_not_by_a_lookup(pg, two_athletes):
    """A check-then-insert loses the race between two schedulers."""
    alice, _ = two_athletes
    review = _open(pg, alice)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coach_review (
                id, user_id, kind, period_start, period_end, status,
                input_hash, state_schema_version, analytics_version,
                collected_at, prompt_version
            )
            SELECT :newid, user_id, kind, period_start, period_end, 'pending',
                   input_hash, state_schema_version, analytics_version,
                   collected_at, prompt_version
            FROM fitness_coach_review WHERE id = :id
        """), {"newid": str(uuid.uuid4()), "id": review.id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_different_prompt_version_is_a_different_question(pg, two_athletes):
    """A prompt change can change the answer, so it must not be folded into
    an existing run — the stored `prompt_version` would then describe a run
    that produced something else.

    But it is also not a parallel current review. There is one current answer
    per period, so the new prompt version has to supersede, and `open_review`
    says so instead of letting a unique-index violation surface.
    """
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.review_audit import ReviewConflict, supersede

    alice, _ = two_athletes
    first = _open(pg, alice)

    with pytest.raises(ReviewConflict) as excinfo:
        _open(pg, alice, prompt_version="fitness_coach_review_v2")
    assert "supersede it" in str(excinfo.value)
    assert excinfo.value.review_id == first.id
    pg.rollback()

    second = supersede(
        pg, alice, first.id, state=a_state(alice),
        prompt_version="fitness_coach_review_v2", kind=ReviewKind.WEEKLY,
    )
    pg.commit()
    assert second.id != first.id
    assert second.prompt_version == "fitness_coach_review_v2"
    assert second.supersedes_id == first.id


@requires_pg
def test_two_athletes_asking_the_same_question_get_separate_reviews(pg, two_athletes):
    alice, bob = two_athletes
    a = _open(pg, alice)
    b = _open(pg, bob, state=a_state(bob))
    assert a.id != b.id
    assert a.user_id == alice and b.user_id == bob


@requires_pg
def test_the_input_hash_ignores_the_collection_timestamp(pg, two_athletes):
    """Otherwise the same week's figures assembled two minutes apart are two
    questions, and the idempotency index never fires."""
    from app.services.fitness.review_audit import input_hash

    alice, _ = two_athletes
    first = a_state(alice)
    second = a_state(alice)
    second = second.model_copy(update={
        "as_of": datetime(2026, 9, 28, 23, 59, tzinfo=UTC),
        "data_revision": "rev-9",
    })
    assert input_hash(first) == input_hash(second)


@requires_pg
def test_the_input_hash_changes_when_a_number_changes(pg, two_athletes):
    from app.services.fitness.review_audit import input_hash

    alice, _ = two_athletes
    assert input_hash(a_state(alice)) != input_hash(a_state(alice, weight=80.1))


# ─────────────────────────────────────────────────────────────────────────
# 3. Corrected data makes a linked revision
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_corrected_data_produces_a_new_review_and_keeps_the_old_one(pg, two_athletes):
    """The old review was a correct reading of the data it had, and it is the
    only record of why a decision was made at the time."""
    from app.schemas.fitness_coach import ReviewKind, ReviewStatus
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, revision_chain, supersede,
    )

    alice, _ = two_athletes
    first = _open(pg, alice)
    mark_running(pg, alice, first.id)
    mark_complete(pg, alice, first.id, output=an_output())
    pg.commit()

    corrected = supersede(
        pg, alice, first.id, state=a_state(alice, weight=80.4),
        prompt_version=PROMPT_VERSION, kind=ReviewKind.WEEKLY,
    )
    pg.commit()

    chain = revision_chain(pg, alice, corrected.id)
    assert [r.revision for r in chain] == [1, 2]
    assert chain[0].id == first.id
    assert chain[0].status is ReviewStatus.COMPLETE
    assert chain[0].summary == "Flat week against a cut target."
    assert chain[1].id == corrected.id


@requires_pg
def test_only_one_review_per_period_is_current(pg, two_athletes):
    from app.schemas.fitness_coach import Period, ReviewKind
    from app.services.fitness.review_audit import find_current_review, supersede

    alice, _ = two_athletes
    first = _open(pg, alice)
    second = supersede(
        pg, alice, first.id, state=a_state(alice, weight=80.4),
        prompt_version=PROMPT_VERSION, kind=ReviewKind.WEEKLY,
    )
    pg.commit()

    current = find_current_review(
        pg, alice, kind=ReviewKind.WEEKLY,
        period=Period(start=PERIOD_START, end=PERIOD_END),
    )
    assert current is not None
    assert current.id == second.id


@requires_pg
def test_a_second_current_review_for_one_period_is_refused(pg, two_athletes):
    """The partial unique index. Two live answers to one question is the
    condition where nothing in the system says which is right."""
    alice, _ = two_athletes
    review = _open(pg, alice)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coach_review (
                id, user_id, kind, period_start, period_end, status,
                input_hash, state_schema_version, analytics_version,
                collected_at, prompt_version
            ) VALUES (
                :id, :uid, 'weekly', :start, :end, 'pending',
                'a-different-hash', 1, 1, NOW(), :prompt
            )
        """), {
            "id": str(uuid.uuid4()), "uid": alice,
            "start": PERIOD_START, "end": PERIOD_END, "prompt": PROMPT_VERSION,
        })
        pg.commit()
    pg.rollback()


@requires_pg
def test_unchanged_data_needs_no_rerun(pg, two_athletes):
    """Re-running would spend a model call to restate a conclusion that has
    not changed."""
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.review_audit import needs_rerun

    alice, _ = two_athletes
    _open(pg, alice)
    assert needs_rerun(
        pg, alice, kind=ReviewKind.WEEKLY, state=a_state(alice),
    ) is None


@requires_pg
def test_changed_data_names_the_review_to_supersede(pg, two_athletes):
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.review_audit import needs_rerun

    alice, _ = two_athletes
    first = _open(pg, alice)
    stale = needs_rerun(
        pg, alice, kind=ReviewKind.WEEKLY, state=a_state(alice, weight=79.8),
    )
    assert stale is not None and stale.id == first.id


@requires_pg
def test_a_review_cannot_supersede_another_athletes_review(pg, two_athletes):
    """A revision of someone else's review would put their numbers into this
    athlete's audit trail."""
    alice, bob = two_athletes
    alices = _open(pg, alice)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coach_review (
                id, user_id, kind, period_start, period_end, status,
                input_hash, state_schema_version, analytics_version,
                collected_at, prompt_version, supersedes_id
            ) VALUES (
                :id, :uid, 'weekly', :start, :end, 'pending',
                'h', 1, 1, NOW(), :prompt, :sup
            )
        """), {
            "id": str(uuid.uuid4()), "uid": bob,
            "start": PERIOD_START, "end": PERIOD_END,
            "prompt": PROMPT_VERSION, "sup": alices.id,
        })
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# The status machine
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_terminal_review_accepts_no_further_transition(pg, two_athletes):
    """Allowing a completed review back to `running` would mean a stored
    conclusion could be silently replaced in place."""
    from app.services.fitness.review_audit import (
        ReviewConflict, mark_complete, mark_running,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    mark_complete(pg, alice, review.id, output=an_output())
    pg.commit()

    with pytest.raises(ReviewConflict) as excinfo:
        mark_running(pg, alice, review.id)
    assert "supersede" in str(excinfo.value)


@requires_pg
def test_a_pending_review_cannot_jump_straight_to_complete(pg, two_athletes):
    """A review that was never claimed cannot have been answered, and a run
    that skipped `running` leaves no record of which worker held it."""
    from app.services.fitness.review_audit import ReviewConflict, mark_complete

    alice, _ = two_athletes
    review = _open(pg, alice)
    with pytest.raises(ReviewConflict):
        mark_complete(pg, alice, review.id, output=an_output())


@requires_pg
def test_a_failure_records_a_category_and_never_a_prompt(pg, two_athletes):
    """A failed review that banked the full prompt would make this table the
    largest copy of the athlete's private data, kept for the least useful
    reason."""
    from app.schemas.fitness_coach import ReviewFailureCategory, ReviewStatus
    from app.services.fitness.review_audit import (
        MAX_ERROR_DETAIL, mark_failed, mark_running,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    failed = mark_failed(
        pg, alice, review.id,
        category=ReviewFailureCategory.INVALID_OUTPUT,
        detail="x" * 5000,
    )
    pg.commit()

    assert failed.status is ReviewStatus.FAILED
    assert failed.error_category is ReviewFailureCategory.INVALID_OUTPUT
    assert len(failed.error_detail) <= MAX_ERROR_DETAIL
    assert failed.summary is None

    columns = {r[0] for r in pg.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'fitness_coach_review'
    """)).fetchall()}
    for forbidden in ("prompt", "prompt_text", "raw_output", "transcript",
                      "messages", "raw_response"):
        assert forbidden not in columns, f"{forbidden} stores the prompt text"


@requires_pg
def test_a_failed_review_has_no_output(pg, two_athletes):
    from app.services.fitness.review_audit import mark_failed, mark_running
    from app.schemas.fitness_coach import ReviewFailureCategory

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    mark_failed(pg, alice, review.id,
                category=ReviewFailureCategory.MODEL_TIMEOUT)
    pg.commit()

    row = pg.execute(text(
        "SELECT output, summary FROM fitness_coach_review WHERE id = :id"
    ), {"id": review.id}).fetchone()
    assert row.output is None
    assert row.summary is None


@requires_pg
def test_insufficient_data_is_its_own_terminal_state(pg, two_athletes):
    """"Not enough data to say anything useful" is a correct and complete
    answer, and the right response is to log more — not to retry the model.
    Folding it into `failed` makes a retry loop chase something no retry can
    fix."""
    from app.schemas.fitness_coach import ReviewStatus
    from app.services.fitness.review_audit import (
        mark_insufficient_data, mark_running,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    out = mark_insufficient_data(
        pg, alice, review.id, detail="two weigh-ins in the window",
    )
    pg.commit()
    assert out.status is ReviewStatus.INSUFFICIENT_DATA
    assert out.status is not ReviewStatus.FAILED


@requires_pg
def test_a_complete_status_requires_an_output_at_the_database_level(
    pg, two_athletes,
):
    """A `complete` row with no output would be read as "the coach had
    nothing to say"."""
    alice, _ = two_athletes
    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coach_review (
                id, user_id, kind, period_start, period_end, status,
                input_hash, state_schema_version, analytics_version,
                collected_at, prompt_version
            ) VALUES (
                :id, :uid, 'weekly', :start, :end, 'complete',
                'h', 1, 1, NOW(), :prompt
            )
        """), {
            "id": str(uuid.uuid4()), "uid": alice,
            "start": PERIOD_START, "end": PERIOD_END, "prompt": PROMPT_VERSION,
        })
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_terminal_reviews_attempt_count_cannot_change(pg, two_athletes):
    from app.services.fitness.review_audit import (
        ReviewConflict, mark_complete, mark_running, record_attempt,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    assert record_attempt(pg, alice, review.id) == 2
    mark_running(pg, alice, review.id)
    mark_complete(pg, alice, review.id, output=an_output())
    pg.commit()

    with pytest.raises(ReviewConflict):
        record_attempt(pg, alice, review.id)


@requires_pg
def test_the_actual_model_is_recorded_separately_from_the_requested_one(
    pg, two_athletes,
):
    """A fallback that answered as the primary makes every later comparison
    between runs meaningless."""
    from app.services.fitness.review_audit import mark_running

    alice, _ = two_athletes
    review = _open(pg, alice, model_requested="qwen3.8-27b")
    running = mark_running(pg, alice, review.id, model_actual="qwen3.5-35b-a3b")
    pg.commit()
    assert running.model_requested == "qwen3.8-27b"
    assert running.model_actual == "qwen3.5-35b-a3b"


# ─────────────────────────────────────────────────────────────────────────
# 4. A recommendation is a proposal
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_recommendation_starts_as_a_proposal(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    assert len(recs) == 1
    assert recs[0].decision_status is DecisionStatus.PROPOSED
    assert recs[0].is_open
    assert recs[0].action.value == "target_revision"
    assert recs[0].action_receipt_id is None
    assert recs[0].applied_revision_id is None


@requires_pg
def test_storing_a_recommendation_changes_no_target(pg, two_athletes):
    """The completion criterion: the schema cannot masquerade as an applied
    change."""
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    record_recommendations(pg, alice, review.id, output)
    pg.commit()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :uid
    """), {"uid": alice}).scalar() == 0


@requires_pg
def test_accepted_without_a_receipt_is_refused_by_the_database(pg, two_athletes):
    """A prompt rule cannot stop a model from claiming it did something. A
    CHECK constraint can."""
    alice, _ = two_athletes
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            UPDATE fitness_coach_recommendation
            SET decision_status = 'accepted', decided_at = NOW(),
                decided_by = 'user'
            WHERE id = :id
        """), {"id": recs[0].id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_rejected_recommendation_may_not_carry_a_receipt(pg, two_athletes):
    """Nothing executed, so there is nothing to point at. A receipt on a
    rejected row would make the audit trail contradict itself."""
    alice, _ = two_athletes
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            UPDATE fitness_coach_recommendation
            SET decision_status = 'rejected', decided_at = NOW(),
                decided_by = 'user', action_receipt_id = 'r-1'
            WHERE id = :id
        """), {"id": recs[0].id})
        pg.commit()
    pg.rollback()


@requires_pg
def test_accepting_through_the_service_requires_the_proof(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.review_audit import (
        decide, mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    with pytest.raises(FitnessDataError) as excinfo:
        decide(pg, alice, recs[0].id, decision=DecisionStatus.ACCEPTED)
    assert "effect it did not have" in str(excinfo.value)
    pg.rollback()


@requires_pg
def test_a_rejection_is_recorded_and_the_row_is_retained(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.review_audit import (
        decide, list_recommendations, mark_complete, mark_running,
        record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    decided = decide(
        pg, alice, recs[0].id, decision=DecisionStatus.REJECTED,
        note="not this week",
    )
    pg.commit()

    assert decided.decision_status is DecisionStatus.REJECTED
    assert decided.decided_at is not None
    assert decided.decision_note == "not this week"
    # Retained, so "what did you suggest and what did I do" stays answerable.
    assert len(list_recommendations(pg, alice, include_expired=True)) == 1


@requires_pg
def test_a_decision_is_recorded_once(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.review_audit import (
        decide, mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    decide(pg, alice, recs[0].id, decision=DecisionStatus.REJECTED)
    pg.commit()

    with pytest.raises(FitnessDataError):
        decide(pg, alice, recs[0].id, decision=DecisionStatus.ACCEPTED,
               applied_revision_id=None)
    pg.rollback()


@requires_pg
def test_an_expired_proposal_is_retained_not_deleted(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.review_audit import (
        expire_stale_recommendations, list_recommendations, mark_complete,
        mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.execute(text("""
        UPDATE fitness_coach_recommendation SET expires_at = NOW() - INTERVAL '1 day'
        WHERE id = :id
    """), {"id": recs[0].id})
    pg.commit()

    assert expire_stale_recommendations(pg, alice) == 1
    pg.commit()

    assert list_recommendations(pg, alice) == []
    retained = list_recommendations(pg, alice, include_expired=True)
    assert len(retained) == 1
    assert retained[0].decision_status is DecisionStatus.EXPIRED


@requires_pg
def test_a_recommendation_cannot_hang_off_another_athletes_review(
    pg, two_athletes,
):
    """§5: an FK to a UUID alone does not enforce ownership. Without the
    trigger this row would be served under Bob's auth carrying Alice's
    numbers."""
    alice, bob = two_athletes
    alices = _open(pg, alice)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            INSERT INTO fitness_coach_recommendation (
                id, review_id, user_id, category, action, title, rationale,
                confidence
            ) VALUES (
                :id, :review, :uid, 'maintain', 'none', 'x', 'y', 'low'
            )
        """), {"id": str(uuid.uuid4()), "review": alices.id, "uid": bob})
        pg.commit()
    pg.rollback()


@requires_pg
def test_a_proposal_records_what_it_was_measured_against(pg, two_athletes):
    """A proposal written against a target the athlete has since changed is
    stale. Without this it would be silently applied over the newer value."""
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    baseline = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=3000, protein_g=200),
    ))

    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(
        pg, alice, review.id, output,
        current_target_revision_id=baseline.id,
    )
    pg.commit()
    assert recs[0].current_target_revision_id == baseline.id


@requires_pg
def test_hold_course_advice_needs_no_proposed_change(pg, two_athletes):
    """"Keep going" is advice, not an absence of advice, and it must be
    storable."""
    from app.schemas.fitness_coach import (
        ConfidenceCategory, RecommendationCategory, ReviewRecommendation,
    )
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    output = an_output(recommendations=[ReviewRecommendation(
        category=RecommendationCategory.MAINTAIN,
        headline="Hold the current targets",
        rationale="The rate is on plan.",
        metric_paths=["weight.velocity_weekly"],
        confidence=ConfidenceCategory.HIGH,
        confidence_basis="six of seven days observed",
    )])
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    assert recs[0].action.value == "none"
    assert recs[0].proposed_change.kind.value == "none"


# ─────────────────────────────────────────────────────────────────────────
# Reads, owner scope and payload bounds
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_trail_answers_why_from_frozen_metrics(pg, two_athletes):
    """The completion criterion: "why calories?" traces to frozen metrics and
    references."""
    from app.services.fitness.review_audit import (
        get_review, mark_complete, mark_running, record_recommendations,
    )

    alice, _ = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id, model_actual="qwen3.8-27b")
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    record_recommendations(pg, alice, review.id, output)
    pg.commit()

    detail = get_review(pg, alice, review.id, with_state=True)
    assert detail.input_state is not None
    # The exact number the recommendation cited, as it stood.
    assert detail.input_state.sections["weight"].metrics["velocity_weekly"].value \
        == pytest.approx(-0.35)
    assert "weight.velocity_weekly" in detail.input_state.metric_paths()
    assert detail.output is not None
    assert detail.recommendations[0].metric_paths == ["weight.velocity_weekly"]
    assert detail.model_actual == "qwen3.8-27b"
    assert detail.analytics_version == 1


@requires_pg
def test_the_state_snapshot_is_opt_in(pg, two_athletes):
    """It is a whole FitnessStateV1; shipping it by default would put the
    athlete's full state into every list response."""
    from app.services.fitness.review_audit import get_review

    alice, _ = two_athletes
    review = _open(pg, alice)
    assert get_review(pg, alice, review.id).input_state is None
    assert get_review(pg, alice, review.id, with_state=True).input_state is not None


@requires_pg
def test_the_stored_snapshot_is_compact(pg, two_athletes):
    """§19.3: a compact complete state, not a giant prompt or a raw
    transcript. An unbounded snapshot per review per week is the shape that
    makes this the largest table in the database."""
    alice, _ = two_athletes
    review = _open(pg, alice)
    size = pg.execute(text("""
        SELECT pg_column_size(input_state) FROM fitness_coach_review
        WHERE id = :id
    """), {"id": review.id}).scalar()
    assert size is not None and size < 65536, f"input_state is {size} bytes"


@requires_pg
def test_one_athlete_cannot_read_anothers_review(pg, two_athletes):
    from app.services.fitness.review_audit import get_review, list_reviews

    alice, bob = two_athletes
    alices = _open(pg, alice)

    # 404, never 403 — confirming the row exists is itself a disclosure.
    with pytest.raises(LookupError):
        get_review(pg, bob, alices.id)
    assert list_reviews(pg, bob) == []
    assert [r.id for r in list_reviews(pg, alice)] == [alices.id]


@requires_pg
def test_one_athlete_cannot_decide_anothers_recommendation(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness.review_audit import (
        decide, mark_complete, mark_running, record_recommendations,
    )

    alice, bob = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    recs = record_recommendations(pg, alice, review.id, output)
    pg.commit()

    with pytest.raises(LookupError):
        decide(pg, bob, recs[0].id, decision=DecisionStatus.REJECTED)


@requires_pg
def test_the_audit_refuses_a_missing_owner(pg, two_athletes):
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.review_audit import list_reviews, open_review

    alice, _ = two_athletes
    with pytest.raises((FitnessDataError, ValueError)):
        list_reviews(pg, "")
    with pytest.raises((FitnessDataError, ValueError)):
        open_review(pg, "", kind=ReviewKind.WEEKLY, state=a_state(alice),
                    prompt_version=PROMPT_VERSION)


@requires_pg
def test_a_state_from_another_owner_is_refused(pg, two_athletes):
    """The state carries its own owner. A mismatch means the caller is about
    to store one athlete's numbers under another's review."""
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.review_audit import open_review

    alice, bob = two_athletes
    with pytest.raises(FitnessDataError):
        open_review(pg, bob, kind=ReviewKind.WEEKLY, state=a_state(alice),
                    prompt_version=PROMPT_VERSION)


@requires_pg
def test_deleting_the_athlete_removes_the_whole_trail(pg, two_athletes):
    """§19 completion: retention follows the owned privacy policy. A review
    holds the athlete's body numbers; it cannot outlive their account."""
    from app.services.fitness.review_audit import (
        mark_complete, mark_running, record_recommendations,
    )

    alice, bob = two_athletes
    review = _open(pg, alice)
    mark_running(pg, alice, review.id)
    output = an_output()
    mark_complete(pg, alice, review.id, output=output)
    record_recommendations(pg, alice, review.id, output)
    pg.commit()

    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": alice})
    pg.commit()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coach_review WHERE id = :id
    """), {"id": review.id}).scalar() == 0
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_coach_recommendation WHERE review_id = :id
    """), {"id": review.id}).scalar() == 0
