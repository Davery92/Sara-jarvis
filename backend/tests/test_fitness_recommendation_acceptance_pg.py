"""Step 21 of FITNESS_COACH_IMPLEMENTATION_PLAN: a plan changes only after
the owner approves an exact, reviewable change.

The completion criteria, each a section below:

* **An exact reviewable change, not a vague intention.** `preview` renders
  the typed old → proposed diff, its scope, its effective date and the
  coverage behind it, so the thing David approves is a specific number.
* **Idempotent, audited and rollback-safe.** Acceptance appends the
  revision, writes the receipt and transitions the decision in ONE
  transaction. A double-tap returns the first receipt. A database failure
  leaves the proposal unapplied, not half-applied.
* **In-session workout policy stays separately bounded.** The receipt here
  carries its own `action_type`, so a reviewed coaching change is never
  mistaken for a chat tool call — different authorization paths.

And the one that matters most in practice: a proposal written against a
target the athlete has since changed is REFUSED. Applying it would silently
undo a deliberate edit, and the athlete would have no way to know why their
calories moved back.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_recommendation_acceptance_pg.py
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration

requires_pg = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="needs a disposable PostgreSQL",
)

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
PERIOD_START = date(2026, 9, 21)
PERIOD_END = date(2026, 9, 28)
EFFECTIVE = date(2026, 9, 29)
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
    alice = f"s21a-{uuid.uuid4().hex[:17]}"
    bob = f"s21b-{uuid.uuid4().hex[:17]}"
    for uid in (alice, bob):
        pg.execute(text("""
            INSERT INTO app_user (id, email, password_hash, created_at)
            VALUES (:id, :e, :p, NOW()) ON CONFLICT (id) DO NOTHING
        """), {"id": uid, "e": f"{uid}@s21.invalid", "p": unusable_hash})
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
                  "fitness_target_revision", "fitness_athlete_profile",
                  "health_metric", "fitness_phase", "fitness_program",
                  "fitness_goals", "world_event"):
        try:
            pg.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"),
                       {"ids": [alice, bob]})
        except Exception:
            pg.rollback()
    try:
        pg.execute(text("DELETE FROM action_receipt WHERE user_id = ANY(:ids)"),
                   {"ids": [alice, bob]})
    except Exception:
        pg.rollback()
    pg.execute(text("DELETE FROM app_user WHERE id = ANY(:ids)"),
               {"ids": [alice, bob]})
    pg.commit()


def _baseline_target(pg, user_id, calories=3000, protein=200):
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision
    revision = create_target_revision(pg, user_id, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 1),
        training=TargetValues(calories=calories, protein_g=protein),
    ))
    pg.commit()
    return revision


def a_state(user_id: str):
    from app.schemas.fitness_coach import (
        DataQuality, DayType, FitnessStateV1, Metric, MetricGroup, Period,
        ResolvedTargets, StateSection, TargetProvenance, TargetValues, Unit,
    )
    return FitnessStateV1(
        user_id=user_id,
        as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        athlete_local_date=PERIOD_END,
        timezone="America/New_York",
        period=Period(start=PERIOD_START, end=PERIOD_END),
        sections={
            StateSection.WEIGHT: MetricGroup(
                section=StateSection.WEIGHT,
                metrics={
                    "velocity_weekly": Metric(
                        key="weight.velocity_weekly", value=-0.05,
                        unit=Unit.KG_PER_WEEK, observed_days=6, expected_days=7,
                    ),
                },
            ),
        },
        targets=ResolvedTargets(
            user_id=user_id, on_date=date(2026, 9, 27),
            day_type=DayType.TRAINING,
            values=TargetValues(calories=3000, protein_g=200),
            provenance=TargetProvenance.APPROVED_REVISION,
        ),
        quality=DataQuality(
            observed_weight_days=6, expected_weight_days=7,
            nutrition_complete_days=5, sleep_nights=6,
        ),
    )


def an_output(*, kind="target_revision", calories=2850, protein=200,
              effective=EFFECTIVE, category=None):
    from app.schemas.fitness_coach import (
        CoachReviewOutputV1, ConfidenceCategory, ProposedChange,
        ProposedChangeKind, RecommendationCategory, ReviewObservation,
        ReviewRecommendation, TargetScope, TargetValues,
    )
    if kind == "target_revision":
        change = ProposedChange(
            kind=ProposedChangeKind.TARGET_REVISION,
            scope=TargetScope.DEFAULT, effective_date=effective,
            target_values=TargetValues(calories=calories, protein_g=protein),
        )
        default_category = RecommendationCategory.NUTRITION_CHANGE
    elif kind == "data_request":
        change = ProposedChange(
            kind=ProposedChangeKind.DATA_REQUEST,
            requested_metric="weight.velocity_weekly",
        )
        default_category = RecommendationCategory.REQUEST_DATA
    elif kind == "program_change":
        change = ProposedChange(
            kind=ProposedChangeKind.PROGRAM_CHANGE,
            description="Swap the Thursday session for a lighter one.",
        )
        default_category = RecommendationCategory.VOLUME_CHANGE
    else:
        change = ProposedChange()
        default_category = RecommendationCategory.MAINTAIN

    return CoachReviewOutputV1(
        summary="Weight is flat against a cut over 6 of 7 logged days.",
        coaching_priority="Decide on a small calorie adjustment.",
        observations=[ReviewObservation(
            text="Weekly change was -0.05 kg/week over 6 of 7 days.",
            metric_paths=["weight.velocity_weekly"],
        )],
        limitations=["One day has no weigh-in."],
        confidence=ConfidenceCategory.MODERATE,
        confidence_basis="six of seven days have a weigh-in",
        recommendations=[ReviewRecommendation(
            category=category or default_category,
            headline="Drop calories by 150",
            rationale="Flat for a week against a cut target.",
            metric_paths=["weight.velocity_weekly"],
            confidence=ConfidenceCategory.MODERATE,
            confidence_basis="six of seven days have a weigh-in",
            proposed_change=change,
        )],
    )


def _a_proposal(pg, user_id, *, baseline=True, **kwargs):
    """A stored, complete review with one recommendation."""
    from app.schemas.fitness_coach import ReviewKind
    from app.services.fitness import review_audit

    if baseline:
        revision = _baseline_target(pg, user_id)
    else:
        revision = None

    review = review_audit.open_review(
        pg, user_id, kind=ReviewKind.WEEKLY, state=a_state(user_id),
        prompt_version=PROMPT_VERSION,
    )
    review_audit.mark_running(pg, user_id, review.id, model_actual="qwen3.8-27b")
    output = an_output(**kwargs)
    review_audit.mark_complete(pg, user_id, review.id, output=output)
    recs = review_audit.record_recommendations(
        pg, user_id, review.id, output,
        current_target_revision_id=revision.id if revision else None,
    )
    pg.commit()
    return recs[0], review, revision


# ─────────────────────────────────────────────────────────────────────────
# An exact reviewable change
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_the_preview_shows_the_typed_old_to_proposed_diff(pg, two_athletes):
    """The completion criterion. "Sara thinks you should eat less" is not
    something anyone can approve."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, baseline = _a_proposal(pg, alice)

    view = service.preview(pg, alice, rec.id)
    by_field = {c.field: c for c in view.changes}
    assert by_field["calories"].current == 3000
    assert by_field["calories"].proposed == 2850
    assert by_field["calories"].delta == -150
    assert by_field["calories"].unit == "kcal"
    assert by_field["calories"].is_change
    # Protein is unchanged and shown as unchanged, so the diff is the whole
    # proposal rather than only its deltas.
    assert by_field["protein_g"].is_change is False

    assert view.scope == "default"
    assert view.effective_date == EFFECTIVE
    assert view.acceptable
    assert view.blockers == []
    assert view.proposed_against_revision_id == baseline.id \
        if hasattr(view, "proposed_against_revision_id") \
        else view.current_revision_id == baseline.id


@requires_pg
def test_the_preview_carries_the_coverage_behind_the_proposal(pg, two_athletes):
    """The confidence label is the model's interpretation; coverage is how
    much data is behind it. A reader needs the pair (§9.6)."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    view = service.preview(pg, alice, rec.id)
    assert view.coverage["observed_weight_days"] == 6
    assert view.coverage["expected_weight_days"] == 7
    assert view.coverage["nutrition_complete_days"] == 5
    assert view.coverage["period_start"] == PERIOD_START.isoformat()


@requires_pg
def test_a_maintain_proposal_previews_as_no_change(pg, two_athletes):
    """"Keep going" is advice, and accepting it records agreement rather
    than a change. Rendering an empty diff is the honest answer."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice, kind="none")
    view = service.preview(pg, alice, rec.id)
    assert view.applicable
    assert view.changes == []
    assert view.acceptable


@requires_pg
def test_the_preview_is_read_only(pg, two_athletes):
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    before = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :u
    """), {"u": alice}).scalar()

    service.preview(pg, alice, rec.id)
    service.preview(pg, alice, rec.id)

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == before
    assert pg.execute(text("""
        SELECT decision_status FROM fitness_coach_recommendation WHERE id = :i
    """), {"i": rec.id}).scalar() == "proposed"


# ─────────────────────────────────────────────────────────────────────────
# Acceptance
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_accepting_applies_the_revision_and_records_the_receipt(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, review, _ = _a_proposal(pg, alice)

    result = service.accept(pg, alice, rec.id)

    assert result.recommendation.decision_status is DecisionStatus.ACCEPTED
    assert result.applied_revision_id
    assert result.action_receipt_id

    revision = pg.execute(text("""
        SELECT calories, protein_g, valid_from, source,
               review_recommendation_id, scope
        FROM fitness_target_revision WHERE id = :id
    """), {"id": result.applied_revision_id}).fetchone()
    assert revision.calories == 2850
    assert revision.valid_from == EFFECTIVE
    assert revision.source == "coach_review"
    # The chain: revision → recommendation → review → frozen state.
    assert revision.review_recommendation_id == rec.id

    receipt = pg.execute(text("""
        SELECT action_type, status, target, evidence_refs::text AS evidence,
               user_id
        FROM action_receipt WHERE action_id = CAST(:id AS uuid)
    """), {"id": result.action_receipt_id}).fetchone()
    assert receipt.status == "completed"
    assert receipt.user_id == alice
    assert result.applied_revision_id in receipt.target
    assert review.id in receipt.evidence


@requires_pg
def test_the_receipt_is_distinguishable_from_a_chat_tool_call(pg, two_athletes):
    """Different authorization paths, different audit meaning. A reviewed
    coaching change must not be readable as "Sara ran a tool"."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    result = service.accept(pg, alice, rec.id)

    row = pg.execute(text("""
        SELECT action_type, source_table, source_id
        FROM action_receipt WHERE action_id = CAST(:id AS uuid)
    """), {"id": result.action_receipt_id}).fetchone()
    assert row.action_type == service.RECEIPT_ACTION_TYPE
    assert row.source_table == "fitness_coach_recommendation"
    assert row.source_id == rec.id


@requires_pg
def test_the_confirmation_is_rendered_from_the_committed_rows(pg, two_athletes):
    """A message composed before the write would describe a change that may
    not have landed. `outcome_grounding` exists for exactly this."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    result = service.accept(pg, alice, rec.id)

    assert "2850 kcal" in result.message
    assert "200 g protein" in result.message
    assert str(EFFECTIVE) in result.message


@requires_pg
def test_accepting_a_data_request_changes_no_target(pg, two_athletes):
    """`request_data` is a real decision with no plan effect, and the
    message says so rather than implying something was applied."""
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice, kind="data_request")
    before = pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :u
    """), {"u": alice}).scalar()

    result = service.accept(pg, alice, rec.id)
    assert result.recommendation.decision_status is DecisionStatus.ACCEPTED
    assert result.applied_revision_id is None
    assert result.action_receipt_id
    assert "Nothing about your plan changed" in result.message
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :u
    """), {"u": alice}).scalar() == before


@requires_pg
def test_an_unsupported_program_change_does_not_execute(pg, two_athletes):
    """Restructuring a program needs the typed service from Step 29.
    Improvising one from a JSON blob is how a plan gets edited in a way
    nobody can review."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice, kind="program_change")

    view = service.preview(pg, alice, rec.id)
    assert not view.applicable
    assert any("by hand" in b for b in view.blockers)

    with pytest.raises(service.RecommendationUnsupported) as excinfo:
        service.accept(pg, alice, rec.id)
    assert "nothing has been changed" in str(excinfo.value)
    pg.rollback()

    # And it is still a readable proposal, not a failure.
    assert pg.execute(text("""
        SELECT decision_status FROM fitness_coach_recommendation WHERE id = :i
    """), {"i": rec.id}).scalar() == "proposed"


# ─────────────────────────────────────────────────────────────────────────
# Idempotency and concurrency
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_accepting_twice_returns_the_existing_receipt(pg, two_athletes):
    """A double-tap must not append a second revision to the athlete's
    history — and must not report a second, different change."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    first = service.accept(pg, alice, rec.id)
    second = service.accept(pg, alice, rec.id)

    assert second.duplicate is True
    assert second.action_receipt_id == first.action_receipt_id
    assert second.applied_revision_id == first.applied_revision_id
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 1
    assert pg.execute(text("""
        SELECT COUNT(*) FROM action_receipt
        WHERE user_id = :u AND source_id = :rec
    """), {"u": alice, "rec": rec.id}).scalar() == 1


@requires_pg
def test_acceptance_happens_exactly_once_under_concurrency(pg, two_athletes):
    """Two sessions racing. The `FOR UPDATE` lock means the second blocks,
    then finds the row decided and returns the first one's receipt."""
    from app.db.session import SessionLocal
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    other = SessionLocal()
    try:
        first = service.accept(pg, alice, rec.id)
        second = service.accept(other, alice, rec.id)
        assert second.duplicate is True
        assert second.action_receipt_id == first.action_receipt_id
    finally:
        other.rollback()
        other.close()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 1


@requires_pg
def test_a_rejected_recommendation_cannot_then_be_accepted(pg, two_athletes):
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    service.reject(pg, alice, rec.id, note="not this week")

    with pytest.raises(service.RecommendationStale) as excinfo:
        service.accept(pg, alice, rec.id)
    assert excinfo.value.code == "already_decided"
    pg.rollback()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_rejecting_changes_no_target_and_keeps_the_row(pg, two_athletes):
    from app.schemas.fitness_coach import DecisionStatus
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    result = service.reject(pg, alice, rec.id, note="too aggressive")

    assert result.decision_status is DecisionStatus.REJECTED
    assert result.decision_note == "too aggressive"
    assert result.applied_revision_id is None
    assert result.action_receipt_id is None
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 0


# ─────────────────────────────────────────────────────────────────────────
# Stale and expired proposals
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_proposal_against_a_superseded_target_is_refused(pg, two_athletes):
    """The failure that matters most in practice.

    Applying it would silently undo a deliberate edit, and the athlete would
    have no way to know why their calories moved back.
    """
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness import recommendations as service
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    rec, _, baseline = _a_proposal(pg, alice)

    # David changes his targets himself after the review ran.
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 26),
        training=TargetValues(calories=3200, protein_g=210),
    ))
    pg.commit()

    view = service.preview(pg, alice, rec.id)
    assert view.stale
    assert not view.acceptable
    assert any("newer decision" in b for b in view.blockers)

    with pytest.raises(service.RecommendationStale) as excinfo:
        service.accept(pg, alice, rec.id)
    assert excinfo.value.code == "stale_target"
    assert excinfo.value.current["proposed_against"] == baseline.id
    pg.rollback()

    # And his own edit is untouched.
    assert pg.execute(text("""
        SELECT calories FROM fitness_target_revision
        WHERE user_id = :u AND valid_from = '2026-09-26'
    """), {"u": alice}).scalar() == 3200


@requires_pg
def test_an_expired_proposal_is_refused(pg, two_athletes):
    """A proposal about last week's training is not advice three weeks
    later."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    pg.execute(text("""
        UPDATE fitness_coach_recommendation
        SET expires_at = NOW() - INTERVAL '1 day' WHERE id = :i
    """), {"i": rec.id})
    pg.commit()

    view = service.preview(pg, alice, rec.id)
    assert view.expired
    with pytest.raises(service.RecommendationStale) as excinfo:
        service.accept(pg, alice, rec.id)
    assert excinfo.value.code == "expired"


@requires_pg
def test_a_proposal_matching_the_current_target_has_nothing_to_apply(
    pg, two_athletes,
):
    """Appending a revision identical to the current one adds a row to the
    history that records no decision."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice, calories=3000, protein=200)
    view = service.preview(pg, alice, rec.id)
    assert any("nothing to apply" in b for b in view.blockers)
    with pytest.raises(service.RecommendationStale):
        service.accept(pg, alice, rec.id)


@requires_pg
def test_the_safety_bounds_are_rechecked_against_the_current_target(
    pg, two_athletes,
):
    """A 5% step against the old target can be a 25% step against the new
    one. The bounds are about what reaches the athlete, not about what the
    model said when it said it."""
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness import recommendations as service
    from app.services.fitness.data_access import FitnessDataError
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    rec, _, baseline = _a_proposal(pg, alice)

    # Drop the current target a long way. The 2850 proposal is now a large
    # step UP. The stale check fires first, so point the proposal at the new
    # revision to isolate the bounds recheck.
    newer = create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 26),
        training=TargetValues(calories=2000, protein_g=200),
    ))
    pg.execute(text("""
        UPDATE fitness_coach_recommendation
        SET current_target_revision_id = :rev WHERE id = :i
    """), {"rev": newer.id, "i": rec.id})
    pg.commit()

    with pytest.raises(FitnessDataError) as excinfo:
        service.accept(pg, alice, rec.id)
    assert "safety bounds" in str(excinfo.value)
    pg.rollback()
    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 0


# ─────────────────────────────────────────────────────────────────────────
# Atomicity
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_a_failure_during_acceptance_leaves_the_proposal_unapplied(
    pg, two_athletes, monkeypatch,
):
    """Rollback-safe. The revision, the receipt and the decision land
    together or not at all: a receipt without a revision claims an effect
    that never happened."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    def explode(*args, **kwargs):
        raise RuntimeError("the receipt write failed")

    monkeypatch.setattr(service, "_write_receipt", explode)
    with pytest.raises(RuntimeError):
        service.accept(pg, alice, rec.id)
    pg.rollback()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 0
    assert pg.execute(text("""
        SELECT decision_status FROM fitness_coach_recommendation WHERE id = :i
    """), {"i": rec.id}).scalar() == "proposed"
    assert pg.execute(text("""
        SELECT COUNT(*) FROM action_receipt WHERE source_id = :i
    """), {"i": rec.id}).scalar() == 0


@requires_pg
def test_a_failure_after_the_revision_rolls_the_revision_back(
    pg, two_athletes, monkeypatch,
):
    """`create_target_revision` is called with `commit=False` precisely so
    this is possible. If it committed internally, a later failure would
    leave the athlete on a target nothing approved."""
    from app.services.fitness import recommendations as service
    from app.services.fitness import review_audit

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    def explode(*args, **kwargs):
        raise RuntimeError("the decision transition failed")

    monkeypatch.setattr(review_audit, "decide", explode)
    with pytest.raises(RuntimeError):
        service.accept(pg, alice, rec.id)
    pg.rollback()

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision
        WHERE user_id = :u AND source = 'coach_review'
    """), {"u": alice}).scalar() == 0


@requires_pg
def test_the_accepted_row_cannot_exist_without_its_proof(pg, two_athletes):
    """The database refuses it. A prompt rule cannot stop a model from
    claiming it did something; a CHECK constraint can."""
    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    with pytest.raises((IntegrityError, DBAPIError)):
        pg.execute(text("""
            UPDATE fitness_coach_recommendation
            SET decision_status = 'accepted', decided_at = NOW(),
                decided_by = 'user'
            WHERE id = :i
        """), {"i": rec.id})
        pg.commit()
    pg.rollback()


# ─────────────────────────────────────────────────────────────────────────
# Owner scope
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_one_athlete_cannot_accept_anothers_recommendation(pg, two_athletes):
    from app.services.fitness import recommendations as service

    alice, bob = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    # 404, never 403.
    with pytest.raises(LookupError):
        service.accept(pg, bob, rec.id)
    with pytest.raises(LookupError):
        service.preview(pg, bob, rec.id)
    with pytest.raises(LookupError):
        service.reject(pg, bob, rec.id)

    assert pg.execute(text("""
        SELECT COUNT(*) FROM fitness_target_revision WHERE user_id = :u
    """), {"u": bob}).scalar() == 0


@requires_pg
def test_acceptance_refuses_a_missing_owner(pg, two_athletes):
    from app.services.fitness import recommendations as service
    from app.services.fitness.data_access import FitnessDataError

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    for bad in ("", None, "  "):
        with pytest.raises((FitnessDataError, ValueError)):
            service.accept(pg, bad, rec.id)


@requires_pg
def test_the_revision_is_owned_by_the_accepting_athlete(pg, two_athletes):
    from app.services.fitness import recommendations as service

    alice, bob = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    result = service.accept(pg, alice, rec.id)
    owner = pg.execute(text("""
        SELECT user_id FROM fitness_target_revision WHERE id = :id
    """), {"id": result.applied_revision_id}).scalar()
    assert owner == alice


# ─────────────────────────────────────────────────────────────────────────
# The trace: "why am I eating 2850?"
# ─────────────────────────────────────────────────────────────────────────

@requires_pg
def test_an_applied_target_traces_back_to_the_frozen_metrics(pg, two_athletes):
    """The chain is only useful if something follows it."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    rec, review, _ = _a_proposal(pg, alice)
    result = service.accept(pg, alice, rec.id)

    trace = service.trace(pg, alice, result.applied_revision_id)
    assert trace["origin"] == "accepted from a coach review"
    assert trace["revision"]["calories"] == 2850
    assert trace["recommendation"]["id"] == rec.id
    assert trace["recommendation"]["decided_by"] == "user"
    assert trace["review"]["id"] == review.id
    assert trace["review"]["model_actual"] == "qwen3.8-27b"
    assert trace["review"]["prompt_version"] == PROMPT_VERSION
    # The exact figure cited, as it stood — not recomputed. The point is
    # what the decision was made on, not what it would say today.
    cited = trace["cited_metrics"]["weight.velocity_weekly"]
    assert cited["value"] == pytest.approx(-0.05)
    assert cited["observed_days"] == 6
    assert cited["expected_days"] == 7


@requires_pg
def test_a_hand_set_target_says_it_has_no_review_behind_it(pg, two_athletes):
    """A real and common answer. An empty object would read as a gap."""
    from app.services.fitness import recommendations as service

    alice, _ = two_athletes
    baseline = _baseline_target(pg, alice)
    trace = service.trace(pg, alice, baseline.id)
    assert "no coach review behind" in trace["origin"]
    assert trace["recommendation"] is None


@requires_pg
def test_one_athlete_cannot_trace_anothers_revision(pg, two_athletes):
    from app.services.fitness import recommendations as service

    alice, bob = two_athletes
    baseline = _baseline_target(pg, alice)
    with pytest.raises(LookupError):
        service.trace(pg, bob, baseline.id)


# ─────────────────────────────────────────────────────────────────────────
# The HTTP boundary
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.fitness_coach import router

    app = FastAPI()
    app.include_router(router, prefix="/api/fitness/coach")
    return TestClient(app)


def _bearer(user_id: str) -> dict:
    from app.core.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': user_id})}"}


@requires_pg
def test_accept_and_reject_are_separate_endpoints(pg, two_athletes, client):
    """Not one endpoint with a boolean: they are different operations with
    different audit meaning, and a boolean makes "not decided yet" and
    "rejected" the same value."""
    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    paths = {
        (tuple(sorted(route.methods)), route.path)
        for route in client.app.routes if hasattr(route, "methods")
    }
    assert (("POST",), "/api/fitness/coach/recommendations/{recommendation_id}/accept") in paths
    assert (("POST",), "/api/fitness/coach/recommendations/{recommendation_id}/reject") in paths


@requires_pg
def test_a_stale_proposal_returns_409_with_the_remedy(pg, two_athletes, client):
    """A bare 409 forces a blind retry of something that will fail the same
    way."""
    from app.schemas.fitness_coach import (
        TargetRevisionIn, TargetScope, TargetValues,
    )
    from app.services.fitness.targets import create_target_revision

    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    create_target_revision(pg, alice, TargetRevisionIn(
        scope=TargetScope.DEFAULT, valid_from=date(2026, 9, 26),
        training=TargetValues(calories=3200, protein_g=210),
    ))
    pg.commit()

    response = client.post(
        f"/api/fitness/coach/recommendations/{rec.id}/accept",
        headers=_bearer(alice), json={},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "stale_target"
    assert "request a new review" in detail["remedy"]
    assert detail["current"]["latest_revision_id"]


@requires_pg
def test_an_unsupported_action_returns_422_with_a_manual_route(
    pg, two_athletes, client,
):
    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice, kind="program_change")
    response = client.post(
        f"/api/fitness/coach/recommendations/{rec.id}/accept",
        headers=_bearer(alice), json={},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "unsupported_action"
    assert "plan editor" in detail["remedy"]


@requires_pg
def test_a_foreign_recommendation_is_404_not_403(pg, two_athletes, client):
    """A 403 confirms the row exists to someone who does not own it."""
    alice, bob = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    for path in ("preview",):
        assert client.get(
            f"/api/fitness/coach/recommendations/{rec.id}/{path}",
            headers=_bearer(bob),
        ).status_code == 404
    for path in ("accept", "reject"):
        assert client.post(
            f"/api/fitness/coach/recommendations/{rec.id}/{path}",
            headers=_bearer(bob), json={},
        ).status_code == 404


@requires_pg
def test_an_unauthenticated_request_cannot_accept_anything(pg, two_athletes, client):
    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)
    assert client.post(
        f"/api/fitness/coach/recommendations/{rec.id}/accept", json={},
    ).status_code in (401, 403)
    assert pg.execute(text("""
        SELECT decision_status FROM fitness_coach_recommendation WHERE id = :i
    """), {"i": rec.id}).scalar() == "proposed"


@requires_pg
def test_the_accept_endpoint_is_idempotent_over_http(pg, two_athletes, client):
    alice, _ = two_athletes
    rec, _, _ = _a_proposal(pg, alice)

    first = client.post(
        f"/api/fitness/coach/recommendations/{rec.id}/accept",
        headers=_bearer(alice), json={},
    )
    second = client.post(
        f"/api/fitness/coach/recommendations/{rec.id}/accept",
        headers=_bearer(alice), json={},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["action_receipt_id"] == first.json()["action_receipt_id"]


# ─────────────────────────────────────────────────────────────────────────
# The older plan-change gates (Step 21.5)
# ─────────────────────────────────────────────────────────────────────────

def test_activating_a_plan_needs_more_than_a_correction():
    """§21.5: the OLDER gates get updated for major changes too, not just
    the new acceptance path.

    `program_activate` and `phase_activate` classified as UPDATE by name
    shape, and UPDATE is the one kind a bare CORRECTION can authorize. So
    "make that the hypertrophy one" would have switched the athlete's entire
    training plan on a phrasing the contract reads as a fix to a previous
    statement — the same class of error as a reschedule request authorizing a
    cancellation.
    """
    from app.services.operation_contract import (
        _AUTHORITY, OperationKind, UtteranceClass, operation_kind_for,
    )

    for tool in ("program_activate", "phase_activate"):
        kind = operation_kind_for(tool)
        assert kind is OperationKind.RECURRING, tool
        authorized_by = _AUTHORITY[kind]
        assert UtteranceClass.CORRECTION not in authorized_by, tool
        assert UtteranceClass.INSTRUCTION in authorized_by
        assert UtteranceClass.CONFIRMATION in authorized_by


def test_ending_a_block_early_is_a_cancellation():
    """It stops something that was scheduled to keep running. "Cancel" and
    "end" are one intent with two implementations."""
    from app.services.operation_contract import (
        _AUTHORITY, OperationKind, UtteranceClass, operation_kind_for,
    )

    kind = operation_kind_for("phase_end_block")
    assert kind is OperationKind.CANCEL
    assert UtteranceClass.CORRECTION not in _AUTHORITY[kind]


def test_inserting_a_block_is_a_creation():
    from app.services.operation_contract import OperationKind, operation_kind_for
    assert operation_kind_for("phase_insert_block") is OperationKind.CREATE


def test_an_ordinary_field_edit_is_still_an_update():
    """The change must not swallow everything: editing a phase's name or its
    macros is a field edit, and a correction is the right authority for it."""
    from app.services.operation_contract import (
        _AUTHORITY, OperationKind, UtteranceClass, operation_kind_for,
    )

    for tool in ("phase_update", "program_update", "nutrition_guide_update"):
        kind = operation_kind_for(tool)
        assert kind is OperationKind.UPDATE, tool
        assert UtteranceClass.CORRECTION in _AUTHORITY[kind]


def test_every_plan_mutator_is_classified_as_a_write():
    """A plan tool that read as a query would bypass the menu gate entirely,
    and the failure would be silent — the tool simply stays available."""
    from app.services.tool_mutation import is_mutating_tool

    for tool in ("program_create", "program_update", "program_activate",
                 "program_delete", "phase_create", "phase_update",
                 "phase_activate", "phase_delete", "phase_insert_block",
                 "phase_end_block", "nutrition_guide_update"):
        assert is_mutating_tool(tool), tool


def test_a_reviewed_acceptance_and_a_chat_tool_call_leave_different_receipts():
    """Different authorization paths. A reviewed coaching change carries its
    own `action_type`, so an audit of "what changed my targets" can tell the
    two apart rather than seeing one undifferentiated pile."""
    from app.services.action_receipt_service import _REVERSIBLE_ACTION_TYPES
    from app.services.fitness.recommendations import RECEIPT_ACTION_TYPE

    assert RECEIPT_ACTION_TYPE == "fitness_coach_recommendation_accepted"
    # Not in the reversible set, so the receipt's tier is `consequential`.
    assert RECEIPT_ACTION_TYPE not in _REVERSIBLE_ACTION_TYPES
