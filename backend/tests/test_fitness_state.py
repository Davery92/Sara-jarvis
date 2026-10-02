"""Step 17 of FITNESS_COACH_IMPLEMENTATION_PLAN: one typed state, and the
properties that make it safe to share.

Four of them get tested here, without a database:

1. **A dependency failure degrades, it does not shrink.** Returning fewer
   metrics because a query broke is indistinguishable from the athlete
   having less data, and a reader would then reason about an absence that is
   really an outage.
2. **The cache key cannot collide across athletes**, and changes when the
   data does. That second property is what makes a missed invalidation cost
   the TTL instead of being unbounded.
3. **Unavailable metrics survive serialization.** A round trip that drops
   `unavailable_reason` turns "we don't know" into "nothing there".
4. **The capsule keeps coverage attached to every number**, and drops whole
   lines rather than truncating one — a number whose caveat was cut off is
   worse than no number.

    backend/scripts/disposable_compose.sh sara-fitness-test \
      -f docker-compose.test.yml run --rm --no-deps backend-test \
      pytest tests/test_fitness_state.py
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.fitness_coach import (
    AthleteGoalOut,
    AthleteLimitationOut,
    DataQuality,
    DayType,
    FitnessStateV1,
    Freshness,
    GoalKind,
    LimitationStatus,
    Metric,
    MetricGroup,
    Period,
    RateBasis,
    ResolvedTargets,
    StateSection,
    TargetProvenance,
    TargetValues,
    Unavailable,
    Unit,
)
from app.services.fitness import state as state_module
from app.services.fitness.state import (
    CACHE_TTL_SECONDS,
    _cache_key,
    _read_cache,
    _safe,
    _write_cache,
    invalidate_fitness_state,
    render_fitness_capsule,
)

UTC = timezone.utc
AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
TODAY = date(2026, 10, 1)


# ── Doubles ───────────────────────────────────────────────────────────────

class FakeRedis:
    """Enough Redis to exercise the cache contract, and nothing more."""

    def __init__(self, *, fail=False):
        self.store = {}
        self.ttls = {}
        self.fail = fail
        self.gets = 0

    def get(self, key):
        self.gets += 1
        if self.fail:
            raise ConnectionError("redis is down")
        return self.store.get(key)

    def setex(self, key, ttl, value):
        if self.fail:
            raise ConnectionError("redis is down")
        self.store[key] = value
        self.ttls[key] = ttl

    def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        return [k for k in list(self.store) if k.startswith(prefix)]

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed


class FakeSession:
    """A session that only records that rollback was asked for."""

    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def a_state(**overrides) -> FitnessStateV1:
    base = dict(
        user_id="athlete-1",
        as_of=AS_OF,
        athlete_local_date=TODAY,
        timezone="America/New_York",
        period=Period(start=TODAY - timedelta(days=7), end=TODAY),
    )
    base.update(overrides)
    return FitnessStateV1(**base)


def a_goal(**overrides) -> AthleteGoalOut:
    base = dict(
        id="g1", user_id="athlete-1", recorded_at=AS_OF,
        kind=GoalKind.CUT, is_primary=True,
        rate_basis=RateBasis.ABSOLUTE, target_rate_kg_week=-0.4,
        valid_from=date(2026, 9, 1),
    )
    base.update(overrides)
    return AthleteGoalOut(**base)


# ─────────────────────────────────────────────────────────────────────────
# 1. A failed dependency degrades
# ─────────────────────────────────────────────────────────────────────────

def test_a_failing_section_is_named_rather_than_silently_omitted():
    """Otherwise an outage reads as an athlete with no data, and the next
    recommendation is built on an absence nobody caused."""
    db = FakeSession()
    degraded = []

    def explode():
        raise RuntimeError("the pain query is broken")

    result = _safe(db, "athlete-1", "pain", explode,
                   MetricGroup(section=StateSection.PAIN), degraded)

    assert degraded == ["pain"]
    assert result.metrics == {}


def test_a_failed_section_rolls_the_transaction_back():
    """In PostgreSQL one failed statement poisons the transaction. Without
    the rollback every LATER section fails too, and the state comes back
    entirely empty for one broken query."""
    db = FakeSession()
    _safe(db, "athlete-1", "weight", lambda: (_ for _ in ()).throw(ValueError("x")),
          None, [])
    assert db.rollbacks == 1


def test_a_successful_section_never_rolls_back_or_records_a_failure():
    db = FakeSession()
    degraded = []
    assert _safe(db, "athlete-1", "weight", lambda: 42, None, degraded) == 42
    assert degraded == []
    assert db.rollbacks == 0


def test_degraded_freshness_is_distinguishable_from_fresh():
    fresh = a_state()
    assert fresh.freshness is Freshness.FRESH
    assert fresh.degraded_dependencies == []

    broken = a_state(freshness=Freshness.DEGRADED, degraded_dependencies=["pain"])
    assert broken.freshness is Freshness.DEGRADED
    assert broken.freshness.value == "degraded"


def test_the_capsule_leads_with_the_degradation_warning():
    """It has to be the first thing a prompt sees, not a footnote after six
    numbers that are missing a seventh."""
    capsule = render_fitness_capsule(
        a_state(freshness=Freshness.DEGRADED,
                degraded_dependencies=["training", "pain"])
    )
    first = capsule.splitlines()[0]
    assert "could not be read" in first
    assert "training" in first and "pain" in first
    assert "incomplete rather than as all there is" in first


# ─────────────────────────────────────────────────────────────────────────
# 2. The cache key
# ─────────────────────────────────────────────────────────────────────────

def test_two_athletes_never_share_a_cache_key():
    """The whole point. One athlete seeing another's body numbers is the
    worst outcome available to this module."""
    args = dict(end=TODAY, timezone_name="America/New_York", span=7,
                sections={StateSection.WEIGHT}, revision="r1")
    alice = _cache_key("alice", **args)
    bob = _cache_key("bob", **args)
    assert alice != bob
    # And the owner is in the key's literal prefix, so a stray SCAN pattern
    # cannot match across athletes either.
    assert alice.startswith("fitness:state:alice:")
    assert bob.startswith("fitness:state:bob:")


@pytest.mark.parametrize("field,value", [
    ("end", date(2026, 9, 30)),
    ("timezone_name", "Europe/London"),
    ("span", 28),
    ("sections", {StateSection.WEIGHT, StateSection.SLEEP}),
    ("revision", "r2"),
])
def test_every_input_that_changes_the_answer_changes_the_key(field, value):
    args = dict(end=TODAY, timezone_name="America/New_York", span=7,
                sections={StateSection.WEIGHT}, revision="r1")
    before = _cache_key("alice", **args)
    args[field] = value
    assert _cache_key("alice", **args) != before, (
        f"{field} changes the state but not the key — a reader would be "
        f"served the previous answer"
    )


def test_section_order_does_not_change_the_key():
    """Asking for weight,sleep and sleep,weight is the same question. A key
    that differed would halve the hit rate for nothing."""
    a = _cache_key("alice", end=TODAY, timezone_name="UTC", span=7,
                   sections={StateSection.WEIGHT, StateSection.SLEEP}, revision="r")
    b = _cache_key("alice", end=TODAY, timezone_name="UTC", span=7,
                   sections={StateSection.SLEEP, StateSection.WEIGHT}, revision="r")
    assert a == b


def test_a_backdated_correction_makes_the_old_entry_unreachable():
    """The data-revision fingerprint is what bounds a missed invalidation.

    A correction to last Tuesday changes the revision, so the key changes
    and the stale entry can never be read again — even if nothing ever
    deletes it.
    """
    redis = FakeRedis()
    args = dict(end=TODAY, timezone_name="UTC", span=7,
                sections={StateSection.WEIGHT})
    before = _cache_key("alice", revision="rev-1", **args)
    _write_cache(redis, before, a_state())
    assert _read_cache(redis, before) is not None

    after_correction = _cache_key("alice", revision="rev-2", **args)
    assert _read_cache(redis, after_correction) is None
    # The stale entry is still physically there; it is simply unreachable.
    assert before in redis.store


def test_the_ttl_is_short_enough_to_bound_a_missed_invalidation():
    redis = FakeRedis()
    key = _cache_key("alice", end=TODAY, timezone_name="UTC", span=7,
                     sections={StateSection.WEIGHT}, revision="r")
    _write_cache(redis, key, a_state())
    assert redis.ttls[key] == CACHE_TTL_SECONDS
    assert CACHE_TTL_SECONDS <= 300, (
        "a long TTL makes a missed invalidation a long-lived wrong answer"
    )


def test_a_redis_outage_costs_a_recompute_and_nothing_else():
    """Redis is expendable; the records are not. A cache failure must not
    surface as a failed read of the athlete's own data."""
    down = FakeRedis(fail=True)
    assert _read_cache(down, "any-key") is None     # no exception
    _write_cache(down, "any-key", a_state())        # no exception
    assert invalidate_fitness_state(down, "alice") == 0


def test_no_cache_client_is_a_supported_configuration():
    assert invalidate_fitness_state(None, "alice") == 0


def test_invalidation_removes_only_this_athletes_entries():
    redis = FakeRedis()
    for user in ("alice", "bob"):
        for revision in ("r1", "r2"):
            key = _cache_key(user, end=TODAY, timezone_name="UTC", span=7,
                             sections={StateSection.WEIGHT}, revision=revision)
            _write_cache(redis, key, a_state(user_id=user))

    assert invalidate_fitness_state(redis, "alice") == 2
    assert all(k.startswith("fitness:state:bob:") for k in redis.store)


def test_an_unreadable_cached_payload_is_discarded_not_guessed_at():
    """A payload written by a previous shape of the state. Recomputing is
    correct; coercing it would silently produce a state missing fields the
    reader will use."""
    redis = FakeRedis()
    redis.store["fitness:state:alice:deadbeef"] = '{"not": "a state"}'
    assert _read_cache(redis, "fitness:state:alice:deadbeef") is None


# ─────────────────────────────────────────────────────────────────────────
# 3. Serialization keeps the unknowns
# ─────────────────────────────────────────────────────────────────────────

def test_an_unavailable_metric_survives_a_round_trip_with_its_reason():
    """Dropping `unavailable_reason` turns "we don't know" into "nothing
    there", and those lead to different advice."""
    group = MetricGroup(section=StateSection.WEIGHT, metrics={
        "velocity_weekly": Metric(
            key="weight.velocity_weekly", unit=Unit.KG_PER_WEEK,
            unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
            observed_days=2, expected_days=7,
            note="two weigh-ins cannot establish a weekly rate",
        ),
    })
    state = a_state(sections={StateSection.WEIGHT: group})

    restored = FitnessStateV1.model_validate_json(state.model_dump_json())
    metric = restored.sections[StateSection.WEIGHT].metrics["velocity_weekly"]
    assert metric.value is None
    assert metric.unavailable_reason is Unavailable.INSUFFICIENT_COVERAGE
    assert metric.observed_days == 2 and metric.expected_days == 7
    assert "cannot establish" in metric.note


def test_the_same_inputs_serialize_to_the_same_bytes():
    """A snapshot that is stable for identical input is what makes a stored
    review input reproducible — and what makes a diff between two days
    mean something."""
    group = MetricGroup(section=StateSection.WEIGHT, metrics={
        "latest": Metric(key="weight.latest", value=81.2, unit=Unit.KG),
    })
    first = a_state(sections={StateSection.WEIGHT: group})
    second = a_state(sections={StateSection.WEIGHT: group})
    assert first.model_dump_json() == second.model_dump_json()


def test_degraded_dependencies_and_quality_notes_both_survive():
    state = a_state(
        freshness=Freshness.DEGRADED,
        degraded_dependencies=["sleep"],
        quality=DataQuality(
            missing_fields=["weight.velocity_weekly: insufficient_coverage"],
            notes=["the goal changed mid-window"],
            nutrition_complete_days=3,
        ),
    )
    restored = FitnessStateV1.model_validate_json(state.model_dump_json())
    assert restored.degraded_dependencies == ["sleep"]
    assert restored.quality.missing_fields == [
        "weight.velocity_weekly: insufficient_coverage"
    ]
    assert restored.quality.notes == ["the goal changed mid-window"]
    assert restored.quality.nutrition_complete_days == 3


def test_metric_paths_lists_exactly_what_a_review_may_cite():
    state = a_state(sections={
        StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
            "latest": Metric(key="weight.latest", value=81.2, unit=Unit.KG),
            "mean_7d": Metric(key="weight.mean_7d", value=81.4, unit=Unit.KG),
        }),
        StateSection.SLEEP: MetricGroup(section=StateSection.SLEEP, metrics={
            "mean_hours": Metric(key="sleep.mean_hours", value=7.1, unit=Unit.HOUR),
        }),
    })
    assert set(state.metric_paths()) == {
        "weight.latest", "weight.mean_7d", "sleep.mean_hours",
    }
    assert "weight.invented_metric" not in state.metric_paths()


# ─────────────────────────────────────────────────────────────────────────
# 4. The capsule
# ─────────────────────────────────────────────────────────────────────────

def test_every_number_in_the_capsule_carries_its_coverage():
    """"81.2 kg" with no "3 of 7 days" reads as a settled fact, and that is
    how a thin figure becomes a decision."""
    capsule = render_fitness_capsule(a_state(sections={
        StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
            "velocity_weekly": Metric(
                key="weight.velocity_weekly", value=-0.35,
                unit=Unit.KG_PER_WEEK, observed_days=4, expected_days=7,
            ),
        }),
    }))
    assert "-0.35" in capsule
    assert "4/7 days observed" in capsule


def test_an_unavailable_velocity_says_it_is_unknown_not_zero():
    capsule = render_fitness_capsule(a_state(sections={
        StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
            "velocity_weekly": Metric(
                key="weight.velocity_weekly", unit=Unit.KG_PER_WEEK,
                unavailable_reason=Unavailable.INSUFFICIENT_COVERAGE,
            ),
        }),
    }))
    assert "not enough weigh-ins" in capsule
    assert "not the same as no change" in capsule


def test_limitations_outrank_trends_when_the_budget_bites():
    """A shoulder that hurts changes what Sara should suggest. A weight trend
    does not, so it is the trend that gets cut."""
    state = a_state(
        goals=[a_goal()],
        limitations=[AthleteLimitationOut(
            id="l1", user_id="athlete-1", status=LimitationStatus.ACTIVE,
            created_at=AS_OF, area="left shoulder", severity_flag="moderate",
            effective_from=date(2026, 9, 20),
        )],
        sections={
            StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
                "latest": Metric(key="weight.latest", value=81.2, unit=Unit.KG,
                                 note="measured 2026-09-30"),
            }),
        },
    )
    full = render_fitness_capsule(state, char_budget=4000)
    assert "left shoulder" in full
    assert "81.2" in full

    tight = render_fitness_capsule(state, char_budget=120)
    assert "left shoulder" in tight
    assert "81.2" not in tight


def test_truncation_drops_whole_lines_rather_than_cutting_one():
    """A half-line can leave a number with its caveat removed, which is
    worse than omitting the number."""
    state = a_state(
        goals=[a_goal()],
        sections={
            StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
                "velocity_weekly": Metric(
                    key="weight.velocity_weekly", value=-0.35,
                    unit=Unit.KG_PER_WEEK, observed_days=4, expected_days=7,
                ),
            }),
        },
    )
    capsule = render_fitness_capsule(state, char_budget=70)
    assert len(capsule) <= 70
    for line in capsule.splitlines():
        # Nothing ends mid-sentence.
        assert line.endswith(".") or line.endswith("]")


def test_a_state_with_nothing_in_it_says_so_rather_than_rendering_empty():
    capsule = render_fitness_capsule(a_state())
    assert "Goal: none recorded." in capsule


def test_the_capsule_flags_targets_with_no_recorded_history():
    """Legacy provenance means the numbers came from a mutable column, so
    "what was I eating in September" cannot be answered from them. A reader
    needs to know that before citing them as a past prescription."""
    state = a_state(targets=ResolvedTargets(
        user_id="athlete-1", on_date=TODAY, day_type=DayType.TRAINING,
        values=TargetValues(calories=3000, protein_g=200),
        provenance=TargetProvenance.LEGACY_PHASE,
    ))
    capsule = render_fitness_capsule(state)
    assert "3000 kcal" in capsule
    assert "200g protein" in capsule
    assert "no recorded history behind these" in capsule


def test_an_approved_revision_is_not_flagged():
    state = a_state(targets=ResolvedTargets(
        user_id="athlete-1", on_date=TODAY, day_type=DayType.TRAINING,
        values=TargetValues(calories=3000, protein_g=200),
        provenance=TargetProvenance.APPROVED_REVISION, revision_id="r1",
        revision_version=3,
    ))
    capsule = render_fitness_capsule(state)
    assert "no recorded history" not in capsule


def test_pain_in_the_capsule_keeps_its_denominator_and_its_disclaimer():
    """"Four of six sessions that were asked about" means something. "Four
    pain reports" does not — and neither is a diagnosis."""
    state = a_state(sections={
        StateSection.PAIN: MetricGroup(section=StateSection.PAIN, items=[{
            "exercise": "Barbell Curl", "sessions_with_pain": 4,
            "sessions_with_report": 6, "sessions_total": 9,
        }]),
    })
    capsule = render_fitness_capsule(state)
    assert "4 of 6" in capsule
    assert "Reported, not diagnosed" in capsule


def test_the_goal_rate_is_rendered_from_the_basis_the_athlete_chose():
    absolute = render_fitness_capsule(a_state(goals=[a_goal()]))
    assert "-0.4 kg/week" in absolute

    percent = render_fitness_capsule(a_state(goals=[a_goal(
        rate_basis=RateBasis.PERCENT, target_rate_kg_week=None,
        target_rate_percent_week=-0.5,
    )]))
    assert "-0.5%/week" in percent
    assert "kg/week" not in percent


def test_a_non_primary_goal_does_not_become_the_headline():
    state = a_state(goals=[
        a_goal(id="g2", is_primary=False, kind=GoalKind.RECOMP,
               rate_basis=RateBasis.NONE, target_rate_kg_week=None),
    ])
    assert "Goal: none recorded." in render_fitness_capsule(state)


def test_the_capsule_never_exceeds_its_budget():
    """A prompt budget that is exceeded is not a budget. Something else in
    the prompt gets silently clipped instead, and which thing is unknowable
    from here."""
    state = a_state(
        goals=[a_goal()],
        limitations=[
            AthleteLimitationOut(
                id=f"l{n}", user_id="athlete-1", status=LimitationStatus.ACTIVE,
                created_at=AS_OF, area=f"area {n}" * 10,
                effective_from=date(2026, 9, 1),
            ) for n in range(5)
        ],
        sections={
            StateSection.WEIGHT: MetricGroup(section=StateSection.WEIGHT, metrics={
                "latest": Metric(key="weight.latest", value=81.2, unit=Unit.KG,
                                 note="x" * 400),
            }),
        },
    )
    for budget in (200, 300, 500, 1500):
        assert len(render_fitness_capsule(state, budget)) <= budget


# ─────────────────────────────────────────────────────────────────────────
# Owner scope is not optional
# ─────────────────────────────────────────────────────────────────────────

def test_the_state_builder_refuses_a_missing_owner():
    """Step 2 exists because a fitness path once defaulted to a shared owner.
    There is no default here, and an empty user id is an error rather than
    "everybody"."""
    from app.services.fitness.data_access import FitnessDataError

    for bad in (None, "", "   "):
        with pytest.raises((FitnessDataError, ValueError)):
            state_module.build_fitness_state(FakeSession(), bad)


def test_the_forbidden_event_payload_keys_cover_the_body_numbers():
    """A world fact is a wider surface than an owned fitness row. The event
    says a weight was recorded; the number stays where the health authority
    rules reach it."""
    from app.services.fitness.events import FORBIDDEN_PAYLOAD_KEYS

    for name in ("value", "weight", "body_weight", "hrv", "calories",
                 "sleep_hours", "heart_rate", "protein_g"):
        assert name in FORBIDDEN_PAYLOAD_KEYS
