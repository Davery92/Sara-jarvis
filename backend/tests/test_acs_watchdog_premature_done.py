"""Tests for the premature-done suppression rule (PR 1).

Covers:
  - Threshold edges for `should_suppress_done` (both tunables, both passing
    and failing in isolation)
  - Tunable overrides via the `tunables._CACHE` mechanism (mirrors how the
    existing watchdog rules read tunable_setting values)

Nudge-wording tests intentionally omitted: pinning prose strings creates
friction for tuning wording without the underlying logic changing. The
three-branch logic in `build_premature_done_nudge` is exercised end-to-end
by the runtime when suppression fires.
"""

from __future__ import annotations

import time

import pytest

from app.services.acs.watchdog import should_suppress_done


# ── Helpers for tunable overrides ──────────────────────────────────────


@pytest.fixture
def tunable_override(monkeypatch):
    """Inject values into the in-process tunables cache for the duration of
    a test. Mirrors the runtime path: get_tunable_int reads from `_CACHE`
    after a TTL check, so freezing _CACHE_LOADED_AT prevents reload races.
    """
    from app.services import tunables as _tun

    original_cache = dict(_tun._CACHE)
    original_loaded_at = _tun._CACHE_LOADED_AT

    def _set(values: dict) -> None:
        _tun._CACHE.update(values)
        _tun._CACHE_LOADED_AT = time.time() + 3600  # far future, no reload

    yield _set

    _tun._CACHE.clear()
    _tun._CACHE.update(original_cache)
    _tun._CACHE_LOADED_AT = original_loaded_at


# ── should_suppress_done — defaults (8 turns, 2 cognitive) ────────────


def test_below_both_thresholds_suppresses() -> None:
    assert should_suppress_done(turn_count=3, cognitive_tool_count=1) is not None


def test_below_turn_threshold_only_suppresses() -> None:
    """Cog count above min, turn count below — turn-count fail, suppress."""
    assert should_suppress_done(turn_count=5, cognitive_tool_count=5) is not None


def test_below_cog_threshold_only_suppresses() -> None:
    """Turn count above min, cog count below — cog-count fail, suppress."""
    assert should_suppress_done(turn_count=20, cognitive_tool_count=1) is not None


def test_at_both_thresholds_passes() -> None:
    """Edge: turn=8, cog=2 — both meet defaults exactly, should NOT suppress."""
    assert should_suppress_done(turn_count=8, cognitive_tool_count=2) is None


def test_well_above_thresholds_passes() -> None:
    assert should_suppress_done(turn_count=50, cognitive_tool_count=20) is None


def test_first_turn_always_suppresses_under_defaults() -> None:
    """Turn 1 is unconditionally below the default min_turns=8."""
    assert should_suppress_done(turn_count=1, cognitive_tool_count=100) is not None


def test_zero_cog_always_suppresses_under_defaults() -> None:
    """cog=0 is unconditionally below default min_cog=2."""
    assert should_suppress_done(turn_count=100, cognitive_tool_count=0) is not None


def test_suppression_reason_includes_thresholds() -> None:
    """Reason string surfaces the thresholds so logs are self-explanatory."""
    reason = should_suppress_done(turn_count=3, cognitive_tool_count=1)
    assert reason is not None
    assert "3 turn" in reason
    assert "1 cognitive tool" in reason
    assert "8" in reason  # default min_turns
    assert "2" in reason  # default min_cog


# ── Tunable overrides — both tunables, both passing ──────────────────


def test_min_turns_tunable_override_passes(tunable_override) -> None:
    """Lowering min_turns to 3 should let a turn=3, cog=2 session pass."""
    tunable_override({
        "acs.watchdog.premature_done_min_turns": 3,
        "acs.watchdog.premature_done_min_cognitive_tools": 2,
    })
    assert should_suppress_done(turn_count=3, cognitive_tool_count=2) is None


def test_min_cog_tunable_override_passes(tunable_override) -> None:
    """Lowering min_cognitive_tools to 1 should let a turn=8, cog=1 session pass."""
    tunable_override({
        "acs.watchdog.premature_done_min_turns": 8,
        "acs.watchdog.premature_done_min_cognitive_tools": 1,
    })
    assert should_suppress_done(turn_count=8, cognitive_tool_count=1) is None


def test_raised_thresholds_suppress_previously_passing(tunable_override) -> None:
    """Raising thresholds suppresses a session that passed under defaults."""
    tunable_override({
        "acs.watchdog.premature_done_min_turns": 20,
        "acs.watchdog.premature_done_min_cognitive_tools": 10,
    })
    assert should_suppress_done(turn_count=8, cognitive_tool_count=2) is not None


def test_both_tunables_override_independently(tunable_override) -> None:
    """Permissive turn-threshold, strict cog-threshold — only the strict one fires."""
    tunable_override({
        "acs.watchdog.premature_done_min_turns": 1,
        "acs.watchdog.premature_done_min_cognitive_tools": 5,
    })
    # turn passes (5 >= 1), cog fails (2 < 5) → suppress
    reason = should_suppress_done(turn_count=5, cognitive_tool_count=2)
    assert reason is not None
    # turn passes (5 >= 1), cog passes (5 >= 5) → pass
    assert should_suppress_done(turn_count=5, cognitive_tool_count=5) is None


