"""Step 20 of FITNESS_COACH_IMPLEMENTATION_PLAN: output validation is
enforced, not requested.

The completion criterion is *"structured output validation is enforceable
beyond prompt instructions"* — so every rule the prompt states is tested
here against the validator, with the prompt removed from the picture. A model
that ignores an instruction has to be stopped by code.

What each section guards, roughly in order of how badly it goes wrong:

* an invented metric citation — a number the athlete will act on that
  nothing measured;
* a diagnosis — a clinical claim from a fitness app, which will be repeated
  to a physio as something Sara said;
* a fabricated citation — indistinguishable from a real one;
* a dangerous or oversized target step;
* confidence that outruns coverage.

No database and no model: these are the pure checks.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_review_output.py
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.fitness_coach import (
    CoachReviewOutputV1,
    ConfidenceCategory,
    DataQuality,
    DayType,
    FitnessStateV1,
    Metric,
    MetricGroup,
    Period,
    ProposedChange,
    ProposedChangeKind,
    Quality,
    RecommendationCategory,
    ResolvedTargets,
    ReviewObservation,
    ReviewRecommendation,
    StateSection,
    TargetProvenance,
    TargetValues,
    Unavailable,
    Unit,
)
from app.services.fitness import safety

UTC = timezone.utc
PERIOD = Period(start=date(2026, 9, 21), end=date(2026, 9, 28))


def a_state(
    *,
    weight_days: int = 6,
    complete_nutrition: int = 5,
    sleep_nights: int = 6,
    velocity: float = -0.35,
    targets: bool = True,
    pain_items=None,
    sessions: int = 4,
) -> FitnessStateV1:
    sections = {
        StateSection.WEIGHT: MetricGroup(
            section=StateSection.WEIGHT,
            metrics={
                "latest": Metric(key="weight.latest", value=81.2, unit=Unit.KG,
                                 observed_days=1, expected_days=1),
                "mean_7d": Metric(key="weight.mean_7d", value=81.4, unit=Unit.KG,
                                  observed_days=weight_days, expected_days=7),
                "velocity_weekly": (
                    Metric(key="weight.velocity_weekly", value=velocity,
                           unit=Unit.KG_PER_WEEK, observed_days=weight_days,
                           expected_days=7)
                    if velocity is not None else
                    Metric(key="weight.velocity_weekly", unit=Unit.KG_PER_WEEK,
                           unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
                           observed_days=2, expected_days=7)
                ),
            },
        ),
        StateSection.NUTRITION: MetricGroup(
            section=StateSection.NUTRITION,
            metrics={
                "calories_mean": Metric(
                    key="nutrition.calories_mean", value=3010, unit=Unit.KCAL,
                    observed_days=complete_nutrition, expected_days=7,
                ),
                "complete_days": Metric(
                    key="nutrition.complete_days", value=complete_nutrition,
                    unit=Unit.COUNT,
                ),
            },
        ),
        StateSection.TRAINING: MetricGroup(
            section=StateSection.TRAINING,
            metrics={
                "sessions_completed": Metric(
                    key="training.sessions_completed", value=sessions,
                    unit=Unit.COUNT,
                ),
            },
        ),
    }
    if pain_items is not None:
        sections[StateSection.PAIN] = MetricGroup(
            section=StateSection.PAIN, items=pain_items,
        )
    return FitnessStateV1(
        user_id="athlete-1",
        as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        athlete_local_date=date(2026, 9, 28),
        timezone="America/New_York",
        period=PERIOD,
        sections=sections,
        targets=ResolvedTargets(
            user_id="athlete-1", on_date=date(2026, 9, 27),
            day_type=DayType.TRAINING,
            values=TargetValues(calories=3000, protein_g=200),
            provenance=TargetProvenance.APPROVED_REVISION,
            revision_id="rev-1",
        ) if targets else None,
        quality=DataQuality(
            observed_weight_days=weight_days, expected_weight_days=7,
            sleep_nights=sleep_nights,
            nutrition_complete_days=complete_nutrition,
        ),
    )


def an_output(
    *,
    summary: str = "Weight is drifting down at 0.35 kg/week across 6 of 7 logged days.",
    priority: str = "Keep the daily weigh-ins going.",
    observations=None,
    recommendations=None,
    limitations=None,
    confidence: ConfidenceCategory = ConfidenceCategory.MODERATE,
    confidence_basis: str = "six of seven days have a weigh-in",
) -> CoachReviewOutputV1:
    if observations is None:
        observations = [ReviewObservation(
            text="Weekly change was -0.35 kg/week over 6 of 7 days.",
            metric_paths=["weight.velocity_weekly"],
        )]
    if recommendations is None:
        recommendations = [ReviewRecommendation(
            category=RecommendationCategory.MAINTAIN,
            headline="Hold the current targets",
            rationale="The rate is within the plan over 6 of 7 logged days.",
            metric_paths=["weight.velocity_weekly"],
            confidence=ConfidenceCategory.MODERATE,
            confidence_basis="six of seven days observed",
        )]
    return CoachReviewOutputV1(
        summary=summary, coaching_priority=priority,
        observations=observations,
        limitations=limitations if limitations is not None else
        ["One day has no weigh-in."],
        confidence=confidence, confidence_basis=confidence_basis,
        recommendations=recommendations,
    )


def a_target_proposal(**values) -> ReviewRecommendation:
    merged = {"calories": 2850, "protein_g": 200}
    merged.update(values)
    return ReviewRecommendation(
        category=RecommendationCategory.NUTRITION_CHANGE,
        headline="Drop calories slightly",
        rationale="Weight has been flat against a cut target over 6 of 7 days.",
        metric_paths=["weight.velocity_weekly"],
        confidence=ConfidenceCategory.MODERATE,
        confidence_basis="six of seven days have a weigh-in",
        proposed_change=ProposedChange(
            kind=ProposedChangeKind.TARGET_REVISION,
            scope="default",
            effective_date=date(2026, 9, 29),
            target_values=TargetValues(**merged),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Parsing: tolerant wrapper, strict content
# ─────────────────────────────────────────────────────────────────────────

def _parse(text):
    from app.services.fitness.reviews import _parse_output
    return _parse_output(text)


def test_a_clean_json_object_parses():
    output, errors = _parse(an_output().model_dump_json())
    assert errors == []
    assert output is not None
    assert output.confidence is ConfidenceCategory.MODERATE


def test_a_fenced_object_parses():
    """Models add fences routinely. Rejecting them wastes a turn on
    formatting noise."""
    body = an_output().model_dump_json()
    output, errors = _parse(f"```json\n{body}\n```")
    assert output is not None and errors == []


def test_leading_chatter_is_tolerated():
    body = an_output().model_dump_json()
    output, _ = _parse(f"Here is the review you asked for:\n{body}")
    assert output is not None


def test_empty_output_is_rejected_with_a_reason():
    output, errors = _parse("")
    assert output is None
    assert errors and "no JSON object" in errors[0]


def test_prose_with_no_json_is_rejected():
    output, errors = _parse("The athlete is doing great, keep it up!")
    assert output is None


def test_malformed_json_is_rejected():
    output, errors = _parse('{"summary": "x", "confidence":}')
    assert output is None


def test_a_json_array_is_not_an_output():
    output, _ = _parse('[{"summary": "x"}]')
    assert output is None


def test_an_invented_field_is_rejected_not_silently_dropped():
    """`extra="forbid"` throughout. A field nobody designed, silently
    dropped, is a model instruction nobody reads and a behaviour nobody
    tested."""
    body = json.loads(an_output().model_dump_json())
    body["applied_change"] = True
    output, errors = _parse(json.dumps(body))
    assert output is None
    assert any("applied_change" in e for e in errors)


def test_a_bad_enum_is_rejected():
    body = json.loads(an_output().model_dump_json())
    body["recommendations"][0]["category"] = "do_a_backflip"
    output, errors = _parse(json.dumps(body))
    assert output is None


def test_a_bad_confidence_value_is_rejected():
    body = json.loads(an_output().model_dump_json())
    body["confidence"] = "very high indeed"
    output, _ = _parse(json.dumps(body))
    assert output is None


def test_a_partial_target_proposal_is_rejected_at_the_schema():
    """A target with no scope or date cannot be accepted, so it must not be
    storable as though it could."""
    body = json.loads(an_output().model_dump_json())
    body["recommendations"][0]["proposed_change"] = {
        "kind": "target_revision",
        "target_values": {"calories": 2800},
    }
    output, errors = _parse(json.dumps(body))
    assert output is None
    assert any("scope" in e or "effective_date" in e for e in errors)


def test_the_output_schema_has_no_executed_action_field():
    """Generating a review changes nothing, so there is nowhere for the model
    to claim it did."""
    fields = set(CoachReviewOutputV1.model_fields)
    for forbidden in ("applied", "applied_change", "executed", "status",
                      "action_taken", "receipt_id"):
        assert forbidden not in fields


# ─────────────────────────────────────────────────────────────────────────
# Reference validation
# ─────────────────────────────────────────────────────────────────────────

def test_an_invented_metric_path_is_rejected():
    """The failure this whole module exists for: a number the athlete will
    act on that nothing measured."""
    state = a_state()
    output = an_output(observations=[ReviewObservation(
        text="Your body fat is down 1.2%.",
        metric_paths=["body_composition.fat_percent"],
    )])
    report = safety.validate_output(output, state)
    assert report.rejected
    assert any("not in the state" in m for m in report.rejections)


def test_a_real_metric_path_passes():
    report = safety.validate_output(an_output(), a_state())
    assert not report.rejected


def test_a_misspelled_path_is_not_guessed_at():
    state = a_state()
    output = an_output(recommendations=[ReviewRecommendation(
        category=RecommendationCategory.MAINTAIN,
        headline="Hold", rationale="Rate is on plan.",
        metric_paths=["weight.velocity_week"],      # missing 'ly'
        confidence=ConfidenceCategory.MODERATE,
        confidence_basis="six of seven days",
    )])
    assert safety.validate_output(output, state).rejected


def test_any_evidence_citation_is_rejected_with_no_corpus_attached():
    """There is no library, so every reference is invented — and an invented
    one reads exactly like a real one."""
    state = a_state()
    output = an_output(recommendations=[ReviewRecommendation(
        category=RecommendationCategory.NUTRITION_CHANGE,
        headline="Raise protein",
        rationale="Higher intake supports retention over 5 of 7 logged days.",
        metric_paths=["nutrition.calories_mean"],
        evidence_refs=["science:1234"],
        confidence=ConfidenceCategory.LOW,
        confidence_basis="five of seven days logged",
    )])
    report = safety.validate_output(output, state)
    assert report.rejected
    assert any("invented" in m for m in report.rejections)


def test_a_numeric_change_resting_only_on_unknowns_is_rejected():
    """"Insufficient coverage" is not evidence of anything. Citing it and
    then proposing a number is the shape of a confident guess."""
    state = a_state(velocity=None, weight_days=2)
    output = an_output(recommendations=[a_target_proposal()])
    report = safety.validate_output(output, state)
    assert report.rejected
    assert any("unavailable" in m or "days of weight data" in m
               for m in report.rejections)


# ─────────────────────────────────────────────────────────────────────────
# Language safety
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "This looks like tendinitis in the elbow.",
    "The pattern suggests shoulder impingement.",
    "You have a strain of the biceps tendon.",
    "That is classic plantar fasciitis.",
])
def test_naming_a_condition_is_rejected(phrase):
    """A clinical claim from a fitness app gets repeated to a physio as
    something Sara said."""
    state = a_state()
    report = safety.validate_output(an_output(summary=phrase), state)
    assert report.rejected
    assert any("condition" in m or "clinical" in m for m in report.rejections)


def test_describing_reported_pain_is_allowed():
    """Pain is data. The rejection is for naming a cause, not for saying the
    athlete's elbow hurt."""
    state = a_state()
    output = an_output(
        summary=(
            "You reported elbow pain on curls in 2 of 4 sessions that were "
            "asked about."
        ),
    )
    assert not safety.validate_output(output, state).rejected


@pytest.mark.parametrize("text", [
    "This is not a diagnosis and nothing here concludes what it is.",
    "I cannot diagnose this; have someone qualified look at it.",
    "You have logged pain in 2 of 4 sessions that were asked about.",
    "You have reported soreness on three of six training days.",
    "You have only two weigh-ins this week, so the rate is unknown.",
])
def test_the_sentences_a_careful_coach_must_be_able_to_say_are_allowed(text):
    """The checks must not reject the disclaimers.

    A bare `diagnos` substring rejected "this is not a diagnosis" and "I
    can't diagnose this" — the two sentences this system most needs to be
    able to say. A bare "you have" rejected "you have logged pain in 2 of 4
    sessions", which is the correct way to report it.
    """
    state = a_state()
    report = safety.validate_output(an_output(summary=text), state)
    assert not report.rejected, report.rejections


@pytest.mark.parametrize("text", [
    "You have an injury in the right elbow.",
    "You've developed something in the shoulder.",
    "You are injured and should stop.",
    "That indicates a problem with the joint.",
    "This is likely a rotator cuff issue.",
    "You were diagnosed with it last year, so avoid pressing.",
])
def test_an_asserted_clinical_judgement_is_still_rejected(text):
    state = a_state()
    report = safety.validate_output(an_output(summary=text), state)
    assert report.rejected, text


@pytest.mark.parametrize("text", [
    "Take ibuprofen and ice for 20 minutes.",
    "Try 400 mg before training.",
    "Ask about a cortisone injection.",
    "Ice it for 15 minutes after each session.",
])
def test_prescribing_treatment_is_rejected(text):
    state = a_state()
    report = safety.validate_output(an_output(priority=text), state)
    assert report.rejected, text
    assert any("treatment" in m for m in report.rejections)


@pytest.mark.parametrize("text", [
    "Take a look at your sleep — 6 of 7 nights are short.",
    "Take a rest day before the next heavy session.",
    "Take a deload week if the elbow is still sore.",
    "Take an extra day between pressing sessions.",
])
def test_ordinary_coaching_language_is_not_treatment_advice(text):
    """The live model's first real output was refused for "take a deload".

    A check that fires on ordinary coaching language is not a safety
    control, it is an outage: every review fails and the athlete sees
    nothing.
    """
    state = a_state()
    report = safety.validate_output(an_output(priority=text), state)
    assert not report.rejected, (text, report.rejections)


def test_recommending_they_see_someone_is_allowed():
    state = a_state()
    output = an_output(
        priority="Get that elbow looked at by someone qualified before "
                 "loading it again.",
    )
    assert not safety.validate_output(output, state).rejected


@pytest.mark.parametrize("text", [
    "Schoenfeld et al. found this works.",
    "A meta-analysis supports this volume.",
    "Research shows 1.6 g/kg is enough.",
    "See the Journal of Strength and Conditioning.",
    "Studies show protein timing matters.",
])
def test_a_fabricated_citation_is_rejected(text):
    state = a_state()
    report = safety.validate_output(an_output(summary=text), state)
    assert report.rejected
    assert any("invented" in m or "cites research" in m
               for m in report.rejections)


def test_an_overclaim_is_downgraded_and_recorded_not_silently_kept():
    state = a_state()
    report = safety.validate_output(
        an_output(priority="This will definitely get you to 80 kg."), state,
    )
    assert not report.rejected
    assert report.downgrades
    assert any("limitations" in str(report.output.limitations).lower() or
               "certainty" in note for note in report.downgrades)
    assert any("certainty" in note for note in report.downgrades)


# ─────────────────────────────────────────────────────────────────────────
# Numeric bounds
# ─────────────────────────────────────────────────────────────────────────

def test_a_dangerous_calorie_target_is_rejected():
    """800 kcal is dangerous whatever the goal, and the prompt is not a
    control."""
    state = a_state()
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=800)]), state,
    )
    assert report.rejected
    assert any("under any circumstances" in m for m in report.rejections)


def test_an_absurdly_high_calorie_target_is_rejected():
    state = a_state()
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=12000)]), state,
    )
    assert report.rejected


def test_a_step_larger_than_the_weekly_limit_is_rejected():
    """A review looks at one week; a 30% cut from one week is an
    overreaction to noise, not a coaching decision."""
    state = a_state()                       # current target is 3000 kcal
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=2000)]), state,
    )
    assert report.rejected
    assert any("single weekly review may propose" in m
               for m in report.rejections)


def test_a_modest_step_is_allowed():
    state = a_state()
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=2850)]), state,
    )
    assert not report.rejected, report.rejections


def test_a_protein_step_beyond_the_limit_is_rejected():
    state = a_state()
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(protein_g=320)]), state,
    )
    assert report.rejected


def test_a_backdated_effective_date_is_rejected():
    """A target cannot be applied to days that have already been eaten — the
    revision would claim to have been in force on days the athlete ate
    against something else."""
    state = a_state()
    rec = a_target_proposal()
    rec = rec.model_copy(update={
        "proposed_change": rec.proposed_change.model_copy(
            update={"effective_date": date(2026, 9, 22)},
        ),
    })
    report = safety.validate_output(an_output(recommendations=[rec]), state)
    assert report.rejected
    assert any("already been eaten" in m for m in report.rejections)


def test_a_change_with_too_few_weigh_ins_is_rejected():
    state = a_state(weight_days=2)
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal()]), state,
    )
    assert report.rejected
    assert any("days of weight data" in m for m in report.rejections)


def test_a_calorie_change_with_too_few_confirmed_days_is_rejected():
    """Adjusting intake from unconfirmed logs adjusts against logging
    habits, not eating."""
    state = a_state(complete_nutrition=1)
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=2850)]), state,
    )
    assert report.rejected
    assert any("logging habits" in m for m in report.rejections)


def test_bounds_still_apply_with_no_current_target():
    """Nothing to step from, so the absolute floors are the only control —
    which is why they are absolute."""
    state = a_state(targets=False)
    report = safety.validate_output(
        an_output(recommendations=[a_target_proposal(calories=700)]), state,
    )
    assert report.rejected


# ─────────────────────────────────────────────────────────────────────────
# Confidence vs coverage
# ─────────────────────────────────────────────────────────────────────────

def test_high_confidence_on_thin_data_is_downgraded_with_a_reason():
    """Coverage and interpretation are separate outputs (§9.6). A confident
    reading of three days is still a reading of three days."""
    state = a_state(weight_days=2, complete_nutrition=1, sleep_nights=2)
    report = safety.validate_output(
        an_output(confidence=ConfidenceCategory.HIGH), state,
    )
    assert not report.rejected
    assert report.output.confidence is ConfidenceCategory.MODERATE
    assert any("lowered to moderate" in note for note in report.downgrades)
    assert any("little data" in note for note in report.output.limitations)


def test_high_confidence_with_real_coverage_stands():
    state = a_state(weight_days=7, complete_nutrition=6, sleep_nights=7)
    report = safety.validate_output(
        an_output(confidence=ConfidenceCategory.HIGH), state,
    )
    assert report.output.confidence is ConfidenceCategory.HIGH


def test_a_concern_may_be_high_confidence_on_thin_data():
    """Severe reported pain needs no further coverage to act on — the
    athlete's own number is the evidence."""
    state = a_state(
        weight_days=1, complete_nutrition=0, sleep_nights=1,
        pain_items=[{
            "exercise": "Barbell Curl", "max_severity": 8,
            "sessions_with_pain": 2, "sessions_with_report": 2,
            "locations": ["elbow"],
        }],
    )
    concern = ReviewRecommendation(
        category=RecommendationCategory.FLAG_CONCERN,
        headline="Get the elbow looked at",
        rationale="You reported 8/10 in 2 of 2 sessions that were asked about.",
        metric_paths=[],
        confidence=ConfidenceCategory.HIGH,
        confidence_basis="your own reported severity",
    )
    report = safety.validate_output(
        an_output(recommendations=[concern]), state,
    )
    assert not report.rejected
    assert report.output.recommendations[0].confidence is ConfidenceCategory.HIGH


# ─────────────────────────────────────────────────────────────────────────
# Pain escalation
# ─────────────────────────────────────────────────────────────────────────

def test_severe_pain_is_escalated_when_the_review_missed_it():
    """A review that noticed an 8/10 and recommended a volume adjustment has
    answered the wrong question."""
    state = a_state(pain_items=[{
        "exercise": "Barbell Curl", "max_severity": 8,
        "sessions_with_pain": 3, "sessions_with_report": 4,
        "locations": ["elbow"], "sides": ["right"],
    }])
    report = safety.validate_output(an_output(), state)
    assert not report.rejected
    assert any("not a volume adjustment" in note for note in report.downgrades)
    first = report.output.recommendations[0]
    assert first.category is RecommendationCategory.FLAG_CONCERN
    assert "looked at" in first.headline


def test_the_injected_concern_names_no_condition_and_no_treatment():
    """It would be absurd for the safety injection to fail the safety
    checks, and an injected diagnosis would be worse than the one rejected."""
    state = a_state(pain_items=[{
        "exercise": "Barbell Curl", "max_severity": 9,
        "sessions_with_pain": 4, "sessions_with_report": 4,
        "locations": ["elbow"], "sides": ["right"],
    }])
    report = safety.validate_output(an_output(), state)
    assert report.output is not None
    # The whole downgraded output must pass the gate again.
    second = safety.validate_output(report.output, state)
    assert not second.rejected, second.rejections
    concern = report.output.recommendations[0]
    assert "not a diagnosis" in concern.rationale
    assert "4 of 4 sessions" in concern.rationale or "4 of\n4" in concern.rationale


def test_ordinary_soreness_is_not_escalated():
    """A 3/10 after a hard session is training feedback. Escalating it is a
    nag for something that is working as intended."""
    state = a_state(pain_items=[{
        "exercise": "Back Squat", "max_severity": 3,
        "sessions_with_pain": 1, "sessions_with_report": 4,
        "locations": ["quad"],
    }])
    report = safety.validate_output(an_output(), state)
    assert report.downgrades == []
    assert all(r.category is not RecommendationCategory.FLAG_CONCERN
               for r in report.output.recommendations)


def test_no_pain_section_escalates_nothing():
    assert safety.pain_escalation(a_state()) is None


def test_a_pain_item_with_no_severity_escalates_nothing():
    """An unrecorded severity is unknown, not severe."""
    state = a_state(pain_items=[{
        "exercise": "Row", "max_severity": None,
        "sessions_with_pain": 1, "sessions_with_report": 1,
    }])
    assert safety.pain_escalation(state) is None


# ─────────────────────────────────────────────────────────────────────────
# Coverage assessment, before the model
# ─────────────────────────────────────────────────────────────────────────

def test_a_rich_week_supports_a_review():
    assert safety.assess_coverage(a_state()).sufficient


def test_a_nearly_empty_week_does_not_and_says_what_would_help():
    """A review generated from two data points produces confident text about
    noise. The right answer is to say what would help."""
    verdict = safety.assess_coverage(
        a_state(weight_days=0, complete_nutrition=0, sleep_nights=0, sessions=0),
    )
    assert not verdict.sufficient
    assert verdict.reason and "Present: none" in verdict.reason
    assert "weigh-ins" in verdict.wanted


def test_one_stream_alone_is_not_enough():
    """Weight with nothing else cannot explain itself: a drop could be a cut
    working or a week of not eating, and the review would guess."""
    verdict = safety.assess_coverage(
        a_state(weight_days=7, complete_nutrition=0, sleep_nights=0, sessions=0),
    )
    assert not verdict.sufficient


def test_two_streams_are_enough():
    verdict = safety.assess_coverage(
        a_state(weight_days=3, complete_nutrition=0, sleep_nights=0, sessions=3),
    )
    assert verdict.sufficient


# ─────────────────────────────────────────────────────────────────────────
# The prompt itself
# ─────────────────────────────────────────────────────────────────────────

def test_the_prompt_carries_a_version_and_a_stable_hash():
    """The version is stored per review. A silent edit would make a stored
    row name a prompt that no longer exists."""
    from app.prompts import fitness_coach_review as prompts
    from app.services.fitness.review_audit import prompt_hash

    assert prompts.PROMPT_VERSION
    assert prompt_hash(prompts.prompt_text()) == prompt_hash(prompts.prompt_text())
    assert len(prompt_hash(prompts.prompt_text())) == 64


def test_the_prompt_lists_only_the_states_own_paths():
    from app.prompts import fitness_coach_review as prompts

    state = a_state()
    user = prompts.build_user_prompt(
        state.model_dump(mode="json"), state.metric_paths(),
    )
    assert "ALLOWED_METRIC_PATHS" in user
    assert "weight.velocity_weekly" in user
    assert "body_composition.fat_percent" not in user


def test_the_prompt_says_there_is_no_research_library():
    """A model with no corpus cites plausible-sounding papers from memory
    unless told not to, and the citation reads exactly like a real one."""
    from app.prompts import fitness_coach_review as prompts

    state = a_state()
    user = prompts.build_user_prompt(
        state.model_dump(mode="json"), state.metric_paths(),
        has_science_corpus=False,
    )
    assert "no curated research library" in user
    assert "never on a named study" in user


def test_the_prompt_caps_its_output():
    """`llama-server` keeps generating after a non-streaming client
    disconnects; an uncapped background call once produced an all-night
    outage."""
    from app.prompts import fitness_coach_review as prompts
    assert 0 < prompts.MAX_OUTPUT_TOKENS <= 4096
    assert prompts.TEMPERATURE <= 0.4


def test_the_compacted_state_drops_chart_series_but_keeps_pain_denominators():
    """A month of daily points is thousands of tokens the metrics already
    summarise, and a model given both quotes the raw points — which is how a
    number with no coverage statement reaches the athlete. Pain items stay:
    they carry the denominator the model has to quote."""
    from app.services.fitness.reviews import compact_for_prompt

    state = a_state(pain_items=[{
        "exercise": "Curl", "max_severity": 4,
        "sessions_with_pain": 1, "sessions_with_report": 3,
    }])
    state.sections[StateSection.WEIGHT].items = [
        {"date": f"2026-09-{d:02d}", "value": 81.0} for d in range(1, 29)
    ]
    payload = compact_for_prompt(state)
    assert payload["sections"]["weight"]["items"] == []
    assert payload["sections"]["pain"]["items"][0]["sessions_with_report"] == 3
    # And the owner never goes into the prompt: the model has no use for it
    # and it is the one field that identifies whose body this is.
    assert "user_id" not in payload
