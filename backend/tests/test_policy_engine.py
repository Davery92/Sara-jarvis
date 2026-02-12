"""
Tests for ActionPolicyEngine (Phase 1 — Cortana Evolution).

Scenarios:
- Unknown tool → Tier 2 deny
- Standing order coverage bypass
- Hard safety gate always blocks Tier 2 without standing order
"""

import pytest
from app.services.autonomy.policy_engine import (
    ActionPolicyEngine,
    PolicyDecision,
    TIER_1_CONFIDENCE_THRESHOLD,
)
from app.services.autonomy.action_tracer import RISK_TIERS, DEFAULT_RISK_TIER, get_risk_tier


@pytest.fixture
def engine():
    return ActionPolicyEngine()


class TestTier0ReadOnly:
    """Tier 0 actions should always be allowed."""

    def test_read_only_always_allowed(self, engine):
        for tool_name, tier in RISK_TIERS.items():
            if tier == 0:
                decision = engine.evaluate(tool_name, confidence=0.0)
                assert decision.decision == "allow", f"{tool_name} should be allowed"
                assert decision.risk_tier == 0

    def test_read_only_low_confidence_still_allowed(self, engine):
        decision = engine.evaluate("check_emails", confidence=0.1)
        assert decision.decision == "allow"

    def test_read_only_no_standing_order_still_allowed(self, engine):
        decision = engine.evaluate("get_weather", confidence=0.0, standing_order_coverage=None)
        assert decision.decision == "allow"


class TestTier1Reversible:
    """Tier 1 actions require confidence >= threshold OR standing order."""

    def test_tier1_high_confidence_allowed(self, engine):
        decision = engine.evaluate("home_light_control", confidence=0.8)
        assert decision.decision == "allow"
        assert decision.risk_tier == 1
        assert "confidence" in decision.reason.lower()

    def test_tier1_at_threshold_allowed(self, engine):
        decision = engine.evaluate("home_light_control", confidence=TIER_1_CONFIDENCE_THRESHOLD)
        assert decision.decision == "allow"

    def test_tier1_below_threshold_deferred(self, engine):
        decision = engine.evaluate("home_light_control", confidence=0.5)
        assert decision.decision == "defer"
        assert decision.risk_tier == 1

    def test_tier1_low_confidence_with_standing_order_allowed(self, engine):
        """Standing order bypasses confidence threshold for Tier 1."""
        decision = engine.evaluate(
            "home_light_control",
            confidence=0.1,
            standing_order_coverage={"order_id": 42, "confidence": 0.9, "risk_tier": 1},
        )
        assert decision.decision == "allow"
        assert decision.standing_order_id == 42
        assert "standing order" in decision.reason.lower()

    def test_tier1_zero_confidence_deferred(self, engine):
        decision = engine.evaluate("send_notification", confidence=0.0)
        assert decision.decision == "defer"


class TestTier2Irreversible:
    """Tier 2 actions only allowed with standing order."""

    def test_unknown_tool_denied(self, engine):
        """Unknown tools default to Tier 2 and are denied."""
        decision = engine.evaluate("launch_missiles", confidence=1.0)
        assert decision.decision == "deny"
        assert decision.risk_tier == DEFAULT_RISK_TIER
        assert "unknown" in decision.reason.lower()

    def test_unknown_tool_high_confidence_still_denied(self, engine):
        decision = engine.evaluate("totally_fake_tool", confidence=0.99)
        assert decision.decision == "deny"

    def test_unknown_tool_with_standing_order_allowed(self, engine):
        """Even unknown tools can be allowed if a standing order covers them."""
        decision = engine.evaluate(
            "totally_fake_tool",
            confidence=0.5,
            standing_order_coverage={"order_id": 99, "confidence": 0.8, "risk_tier": 2},
        )
        assert decision.decision == "allow"
        assert decision.standing_order_id == 99

    def test_get_risk_tier_unknown_returns_default(self):
        assert get_risk_tier("nonexistent_tool") == DEFAULT_RISK_TIER
        assert DEFAULT_RISK_TIER == 2

    def test_get_risk_tier_known_tools(self):
        assert get_risk_tier("check_emails") == 0
        assert get_risk_tier("home_light_control") == 1


class TestHardSafetyGate:
    """Hard safety gate — always active, independent of flags."""

    def test_tier2_blocked_by_hard_gate(self, engine):
        """Tier 2 actions are always blocked by the hard safety gate."""
        decision = engine.evaluate_hard_safety_gate("some_unknown_tool")
        assert decision is not None
        assert decision.decision == "deny"
        assert "hard safety gate" in decision.reason.lower()

    def test_tier0_passes_hard_gate(self, engine):
        """Tier 0 actions pass through the hard safety gate."""
        decision = engine.evaluate_hard_safety_gate("check_emails")
        assert decision is None  # None means no block

    def test_tier1_passes_hard_gate(self, engine):
        """Tier 1 actions pass through the hard safety gate."""
        decision = engine.evaluate_hard_safety_gate("home_light_control")
        assert decision is None

    def test_hard_gate_all_known_tier0_pass(self, engine):
        for tool_name, tier in RISK_TIERS.items():
            if tier == 0:
                assert engine.evaluate_hard_safety_gate(tool_name) is None, \
                    f"Tier 0 tool {tool_name} should pass hard gate"

    def test_hard_gate_all_known_tier1_pass(self, engine):
        for tool_name, tier in RISK_TIERS.items():
            if tier == 1:
                assert engine.evaluate_hard_safety_gate(tool_name) is None, \
                    f"Tier 1 tool {tool_name} should pass hard gate"


class TestStandingOrderCoverage:
    """Test is_covered_by_standing_order matching logic."""

    def test_matching_action_type(self, engine):
        orders = [
            {"id": 1, "status": "active", "action_type": "home_light_control",
             "action_config": {}, "confidence": 0.8, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order("home_light_control", {}, orders)
        assert coverage is not None
        assert coverage["order_id"] == 1

    def test_matching_tool_in_config(self, engine):
        orders = [
            {"id": 2, "status": "active", "action_type": "custom",
             "action_config": {"tool": "send_notification"}, "confidence": 0.7, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order("send_notification", {}, orders)
        assert coverage is not None
        assert coverage["order_id"] == 2

    def test_entity_mismatch_not_covered(self, engine):
        orders = [
            {"id": 3, "status": "active", "action_type": "home_light_control",
             "action_config": {"entity_id": "light.kitchen"}, "confidence": 0.8, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order(
            "home_light_control", {"entity_id": "light.office"}, orders
        )
        assert coverage is None

    def test_entity_match_covered(self, engine):
        orders = [
            {"id": 4, "status": "active", "action_type": "home_light_control",
             "action_config": {"entity_id": "light.office"}, "confidence": 0.9, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order(
            "home_light_control", {"entity_id": "light.office"}, orders
        )
        assert coverage is not None
        assert coverage["order_id"] == 4

    def test_inactive_order_ignored(self, engine):
        orders = [
            {"id": 5, "status": "paused", "action_type": "home_light_control",
             "action_config": {}, "confidence": 0.8, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order("home_light_control", {}, orders)
        assert coverage is None

    def test_no_orders(self, engine):
        coverage = engine.is_covered_by_standing_order("home_light_control", {}, [])
        assert coverage is None

    def test_order_without_entity_covers_any_entity(self, engine):
        """Standing order without entity restriction covers any entity."""
        orders = [
            {"id": 6, "status": "active", "action_type": "home_light_control",
             "action_config": {}, "confidence": 0.8, "risk_tier": 1},
        ]
        coverage = engine.is_covered_by_standing_order(
            "home_light_control", {"entity_id": "light.anywhere"}, orders
        )
        assert coverage is not None
