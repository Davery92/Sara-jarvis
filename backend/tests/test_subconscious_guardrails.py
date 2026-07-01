"""
THE SYSTEM — guardrail tests for Tier 0 promotion decisions.

Verifies the two non-negotiable collapse-guardrails from THE_SYSTEM_DESIGN.md §3.4:
  1. Anomaly override: learned suppression can never mute a genuine anomaly.
  2. Exploration floor: a fully-suppressed cell still samples occasionally.

Pure unit tests against `decide_promotion` — no DB, no randomness (roll is injected).
"""

from app.services.subconscious import decide_promotion, compute_relevance


def test_anomaly_always_overrides_even_at_max_learned_suppression():
    """A suppressed cell (threshold near THETA_MAX) still promotes a genuine anomaly."""
    promoted, reason = decide_promotion(
        significance=0.95, threshold=0.95, anomaly_floor=0.92, explore_rate=0.1, roll=0.99,
    )
    assert promoted is True
    assert reason == "override"


def test_anomaly_override_holds_even_if_threshold_drifted_above_anomaly_floor():
    """Pathological case: threshold > anomaly_floor. Override still checked first."""
    promoted, reason = decide_promotion(
        significance=0.93, threshold=0.97, anomaly_floor=0.92, explore_rate=0.1, roll=0.99,
    )
    assert promoted is True
    assert reason == "override"


def test_below_floor_and_below_threshold_and_no_explore_roll_stays_silent():
    promoted, reason = decide_promotion(
        significance=0.5, threshold=0.7, anomaly_floor=0.92, explore_rate=0.1, roll=0.5,
    )
    assert promoted is False
    assert reason == "subthreshold"


def test_exploration_floor_fires_even_when_fully_suppressed():
    """A quieted domain (threshold near max) still surfaces via the exploration roll —
    this is what prevents self-reinforcing blindness (silence -> no data -> never recover)."""
    promoted, reason = decide_promotion(
        significance=0.1, threshold=0.95, anomaly_floor=0.92, explore_rate=0.1, roll=0.05,
    )
    assert promoted is True
    assert reason == "exploration"


def test_exploration_roll_miss_stays_silent():
    promoted, reason = decide_promotion(
        significance=0.1, threshold=0.95, anomaly_floor=0.92, explore_rate=0.1, roll=0.5,
    )
    assert promoted is False
    assert reason == "subthreshold"


def test_significance_crossing_learned_threshold_promotes_as_anomaly():
    promoted, reason = decide_promotion(
        significance=0.75, threshold=0.7, anomaly_floor=0.92, explore_rate=0.1, roll=0.99,
    )
    assert promoted is True
    assert reason == "anomaly"


def test_relevance_boosts_starved_domains_when_focused():
    assert compute_relevance("work", "focused") == 1.0
    assert compute_relevance("goals", "focused") > compute_relevance("goals", "away")


def test_relevance_gives_no_lift_to_saturated_domains():
    assert compute_relevance("health", "focused") == 0.0
    assert compute_relevance("home", "available") == 0.0


def test_relevance_zero_for_unlisted_domain_while_asleep():
    assert compute_relevance("comms", "asleep") == 0.0
