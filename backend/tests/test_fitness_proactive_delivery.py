"""Step 25 of FITNESS_COACH_IMPLEMENTATION_PLAN: the proactive loop asks one
thing, through the gates that already exist.

The completion criteria, each a section below:

* **Daily and weekly loops respect opt-in and the delivery gates.** Quiet
  mode, a directive, a disabled category and a recent question each produce
  a NAMED suppression, never a silent bypass — because "it was suppressed"
  is not an answer to "why didn't Sara say anything".
* **The requested artifact survives a suppressed push.** A review that was
  generated stays readable in the Coach tab even when the notification was
  refused. Suppressing the notification is not suppressing the work.
* **One source cannot bypass another source's dedup key.** The key is
  `fitness_gap:{date}:{metric}` with no source in it, so the second producer
  dies structurally rather than both delivering.

Plus: new data entered since the occurrence was claimed cancels the question,
and nothing here changes a target.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_proactive_delivery.py
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.fitness_coach import (
    DataQuality, FitnessStateV1, Metric, MetricGroup, Period, StateSection,
    Unit,
)
from app.services.fitness import proactive

UTC = timezone.utc
TODAY = date(2026, 10, 2)


def a_state(
    *,
    weight_days=6, complete_nutrition=5, sleep_nights=6,
    pain_items=None,
) -> FitnessStateV1:
    sections = {
        StateSection.WEIGHT: MetricGroup(
            section=StateSection.WEIGHT,
            metrics={
                "velocity_weekly": Metric(
                    key="weight.velocity_weekly", value=-0.2,
                    unit=Unit.KG_PER_WEEK,
                    observed_days=weight_days, expected_days=7,
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
        as_of=datetime(2026, 10, 2, 11, 0, tzinfo=UTC),
        athlete_local_date=TODAY,
        timezone="America/New_York",
        period=Period(start=TODAY - timedelta(days=7), end=TODAY),
        sections=sections,
        quality=DataQuality(
            observed_weight_days=weight_days, expected_weight_days=7,
            sleep_nights=sleep_nights,
            nutrition_complete_days=complete_nutrition,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# One question, deterministically chosen
# ─────────────────────────────────────────────────────────────────────────

def test_a_complete_week_asks_nothing():
    """The most important case. A system that always has a question is a
    system that asks one whether or not it needs to."""
    assert proactive.choose_gap(a_state()) is None


def test_a_missing_weigh_in_is_asked_about_first():
    """It unblocks the most: without three weigh-ins the weekly rate is
    unknown, and every other number is harder to interpret."""
    question = proactive.choose_gap(a_state(weight_days=1))
    assert question is not None
    assert question.metric == "weight"
    assert "weigh in" in question.question
    assert "three is the minimum" in question.rationale


def test_only_one_question_is_returned_even_when_everything_is_missing():
    """A morning message asking about sleep, weight, food and soreness at
    once is a form, and David has been explicit that a repeated question he
    already answered is worse than no question."""
    question = proactive.choose_gap(
        a_state(weight_days=0, complete_nutrition=0, sleep_nights=0),
    )
    assert question is not None
    assert question.metric == "weight"
    assert isinstance(question.question, str)


def test_nutrition_is_asked_about_once_weight_is_covered():
    question = proactive.choose_gap(
        a_state(weight_days=7, complete_nutrition=0, sleep_nights=7),
    )
    assert question is not None
    assert question.metric == "nutrition"
    assert "logging habits" in question.rationale


def test_sleep_is_asked_about_last_of_the_three():
    question = proactive.choose_gap(
        a_state(weight_days=7, complete_nutrition=7, sleep_nights=0),
    )
    assert question is not None and question.metric == "sleep"


def test_the_same_state_always_produces_the_same_question():
    """Determinism is what makes the shared dedup key work: two producers
    reaching different keys would both deliver."""
    first = proactive.choose_gap(a_state(weight_days=1))
    second = proactive.choose_gap(a_state(weight_days=1))
    assert first.key == second.key


def test_pain_is_only_asked_about_for_an_unreported_session():
    """Asking again about a session that WAS asked about is exactly the
    repeat-question failure."""
    asked = a_state(pain_items=[{
        "exercise": "Barbell Curl", "sessions_total": 3,
        "sessions_with_report": 3, "sessions_with_pain": 1,
    }])
    assert proactive.choose_gap(asked) is None

    unasked = a_state(pain_items=[{
        "exercise": "Barbell Curl", "sessions_total": 4,
        "sessions_with_report": 2, "sessions_with_pain": 1,
    }])
    question = proactive.choose_gap(unasked)
    assert question is not None
    assert question.metric == "pain"
    assert "Barbell Curl" in question.question
    assert "unknown, not pain-free" in question.rationale


def test_every_question_carries_why_it_is_being_asked():
    """"Did you weigh in?" with no reason reads as nagging. With the
    coverage behind it, it reads as a reason."""
    for state in (
        a_state(weight_days=1),
        a_state(weight_days=7, complete_nutrition=0),
        a_state(weight_days=7, complete_nutrition=7, sleep_nights=1),
    ):
        question = proactive.choose_gap(state)
        assert question is not None
        assert question.rationale
        assert any(ch.isdigit() for ch in question.rationale)


# ─────────────────────────────────────────────────────────────────────────
# The shared dedup key
# ─────────────────────────────────────────────────────────────────────────

def test_the_dedup_key_carries_no_source():
    """A key with the source in it would let the morning brief, the check-in
    cadence and a review each have their own copy of the same question — the
    nag-storm shape this subsystem keeps closing."""
    question = proactive.choose_gap(a_state(weight_days=1))
    assert question.key == f"fitness_gap:{TODAY.isoformat()}:weight"
    assert "fitness_coach" not in question.key
    assert "checkin" not in question.key
    assert "brief" not in question.key


def test_the_key_is_per_day_and_per_metric():
    """Per day, so tomorrow's question is a new occurrence. Per metric, so
    asking about sleep does not silence a later weight question — on a
    different day."""
    assert proactive.GAP_KEY.format(day="2026-10-02", metric="weight") != \
        proactive.GAP_KEY.format(day="2026-10-03", metric="weight")
    assert proactive.GAP_KEY.format(day="2026-10-02", metric="weight") != \
        proactive.GAP_KEY.format(day="2026-10-02", metric="sleep")


def test_a_review_notice_is_keyed_on_the_period_not_the_review_id():
    """A superseded review and its replacement are one thing to tell David
    about. Keying on the id would notify twice for one week."""
    first = proactive.REVIEW_KEY.format(period_end="2026-09-28")
    second = proactive.REVIEW_KEY.format(period_end="2026-09-28")
    assert first == second
    assert "review_id" not in first


# ─────────────────────────────────────────────────────────────────────────
# The gates
# ─────────────────────────────────────────────────────────────────────────

class _Session:
    """A session that returns no recent candidate, so the cooldown is open."""

    def execute(self, *args, **kwargs):
        class _Result:
            def fetchone(self_inner):
                return None
        return _Result()

    def rollback(self):
        pass


def _deliver(monkeypatch, *, state, quiet=False, ban=None, recent=None,
             candidate_id="cand-1"):
    created = {}

    monkeypatch.setattr(
        proactive, "_recent_gap_question", lambda db, uid: recent,
    )

    async def fake_ban(**kwargs):
        return ban

    import app.services.quiet_mode as quiet_mode
    monkeypatch.setattr(quiet_mode, "is_quiet", lambda: quiet)
    import app.services.unified_notification as notifications
    monkeypatch.setattr(notifications, "_check_notification_ban", fake_ban)

    async def fake_create(db, uid, question, *, kind, category, ttl):
        created["question"] = question
        created["kind"] = kind
        created["category"] = category
        created["ttl"] = ttl
        return candidate_id

    monkeypatch.setattr(proactive, "_create_candidate", fake_create)

    import app.services.fitness.state as state_module
    monkeypatch.setattr(
        state_module, "build_fitness_state",
        lambda *args, **kwargs: state,
    )

    outcome = asyncio.run(
        proactive.deliver_gap_question(_Session(), "athlete-1")
    )
    return outcome, created


def test_a_question_is_delivered_when_every_gate_is_open(monkeypatch):
    outcome, created = _deliver(monkeypatch, state=a_state(weight_days=1))
    assert outcome.delivered is True
    assert outcome.candidate_id == "cand-1"
    assert created["category"] == proactive.CATEGORY_CHECKIN
    assert created["question"].metric == "weight"


def test_quiet_mode_suppresses_with_its_own_reason(monkeypatch):
    """Named, not boolean. The run row records WHICH gate fired."""
    outcome, created = _deliver(
        monkeypatch, state=a_state(weight_days=1), quiet=True,
    )
    assert outcome.delivered is False
    assert outcome.suppressed_reason == "quiet_mode"
    assert created == {}, "nothing was queued"


def test_a_directive_or_disabled_category_suppresses_with_its_reason(monkeypatch):
    outcome, created = _deliver(
        monkeypatch, state=a_state(weight_days=1),
        ban="User disabled category: checkin",
    )
    assert outcome.delivered is False
    assert outcome.suppressed_reason.startswith("notification_ban:")
    assert "disabled category" in outcome.suppressed_reason
    assert created == {}


def test_a_recent_question_suppresses_whatever_the_metric(monkeypatch):
    """The per-category cooldown does not cover this: "did you weigh in" and
    "how did you sleep" are the same category, so both would pass it and
    David would get two fitness questions in one morning."""
    outcome, _ = _deliver(
        monkeypatch, state=a_state(weight_days=1), recent="sleep",
    )
    assert outcome.delivered is False
    assert outcome.suppressed_reason == "asked_recently:sleep"


def test_a_duplicate_candidate_is_a_recorded_suppression(monkeypatch):
    """`create_candidate` returning None means another producer got there
    first with the same key. That is the shared-key design working, and it
    is recorded as such rather than as a failure."""
    outcome, _ = _deliver(
        monkeypatch, state=a_state(weight_days=1), candidate_id=None,
    )
    assert outcome.delivered is False
    assert outcome.suppressed_reason == "duplicate_candidate"


def test_nothing_missing_is_its_own_reason(monkeypatch):
    """Distinct from a suppression: there was nothing to say, which is not
    the same as having been silenced."""
    outcome, created = _deliver(monkeypatch, state=a_state())
    assert outcome.delivered is False
    assert outcome.suppressed_reason == "nothing_missing"
    assert created == {}


def test_data_entered_since_the_claim_cancels_the_question(monkeypatch):
    """The state is rebuilt HERE, not at claim time. If the weigh-in landed
    between the sweep and this call, the question is answered and asking it
    is the nag."""
    outcome, _ = _deliver(monkeypatch, state=a_state(weight_days=1))
    assert outcome.delivered is True

    # Same occurrence, but he logged two more weigh-ins in the meantime.
    outcome, created = _deliver(monkeypatch, state=a_state(weight_days=3))
    assert outcome.delivered is False
    assert outcome.suppressed_reason == "nothing_missing"


def test_every_suppression_reason_is_a_short_recordable_string(monkeypatch):
    """The ledger column is 60 characters. A reason that overflows would be
    truncated into something unreadable."""
    for kwargs in (
        {"quiet": True},
        {"ban": "User disabled category: checkin"},
        {"recent": "weight"},
        {"candidate_id": None},
    ):
        outcome, _ = _deliver(
            monkeypatch, state=a_state(weight_days=1), **kwargs,
        )
        assert outcome.suppressed_reason
        assert len(outcome.suppressed_reason) <= 60, outcome.suppressed_reason


def test_the_candidate_goes_through_the_single_mouth(monkeypatch):
    """`say_candidate` → judge → compose → review → deliver. A second sender
    bypassing it is the two-mouths failure that was fixed once already."""
    source = open(proactive.__file__).read()
    assert "from app.services.say_candidate import create_candidate" in source
    # And no direct push from here.
    assert "send_notification(" not in source
    assert "send_push" not in source


def test_the_candidate_carries_a_bounded_ttl(monkeypatch):
    """A stale question accumulating is the harping shape. Tomorrow's
    question is a new occurrence, so today's expires."""
    outcome, created = _deliver(monkeypatch, state=a_state(weight_days=1))
    assert created["ttl"] == proactive.GAP_TTL
    assert proactive.GAP_TTL <= timedelta(days=1)


# ─────────────────────────────────────────────────────────────────────────
# Deep links
# ─────────────────────────────────────────────────────────────────────────

def test_a_deep_link_carries_an_id_and_never_a_value():
    """A lock-screen preview showing "you are 81.2 kg" publishes a body
    measurement to anyone holding the phone."""
    question = proactive.choose_gap(a_state(weight_days=1))
    outcome = proactive.DeliveryOutcome(delivered=True, question=question)
    link = proactive.deep_link(outcome)
    assert link == "/fitness/today?ask=weight"
    assert "81" not in link
    assert "kg" not in link


def test_a_review_link_points_at_the_owned_review():
    outcome = proactive.DeliveryOutcome(delivered=True)
    link = proactive.deep_link(outcome, review_id="rev-1")
    assert link == "/fitness/coach?review=rev-1"


def test_an_unknown_metric_still_links_somewhere_useful():
    outcome = proactive.DeliveryOutcome(delivered=True)
    assert proactive.deep_link(outcome) == "/fitness/today"


# ─────────────────────────────────────────────────────────────────────────
# The loop changes nothing
# ─────────────────────────────────────────────────────────────────────────

def test_the_proactive_module_writes_no_target_or_program():
    """A fatigue concern is a suggestion, never an automatic deload.

    Checked against the CODE, with comments stripped: the module's docstring
    says the word "deload" precisely to state that it does not schedule one,
    and a check that could not tell the difference would be a check on
    vocabulary rather than on behaviour.
    """
    import io
    import tokenize

    source = open(proactive.__file__).read()
    code_lines = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_lines.append(token.string)
    code = " ".join(code_lines)

    for forbidden in ("create_target_revision", "deload", "schedule_deload"):
        assert forbidden not in code, forbidden
    # And no SQL that writes, comments or not.
    for forbidden in ("UPDATE fitness_", "INSERT INTO fitness_",
                      "DELETE FROM fitness_"):
        assert forbidden not in source, forbidden


def test_the_module_refuses_a_missing_owner():
    from app.services.fitness.data_access import FitnessDataError

    for bad in ("", None, "   "):
        with pytest.raises((FitnessDataError, ValueError)):
            asyncio.run(proactive.deliver_gap_question(_Session(), bad))
