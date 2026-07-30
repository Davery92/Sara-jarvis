"""
Tests for confidence_ladder.py (Arc 5.2) — the one shared mapping from a raw
confidence float (PKG's 0-0.99, life_fact's 0-1, episode's 0-1 importance) to
the one graduated tier every recall trace now reports through.
"""
from app.services.confidence_ladder import CONFIRMED, INFERRED, OBSERVED, life_fact_tier, tier_from_confidence


class TestTierFromConfidence:
    def test_high_value_is_confirmed(self):
        assert tier_from_confidence(0.9) == CONFIRMED

    def test_boundary_at_confirmed_threshold_is_confirmed(self):
        assert tier_from_confidence(0.75) == CONFIRMED

    def test_mid_value_is_inferred(self):
        assert tier_from_confidence(0.5) == INFERRED

    def test_boundary_at_inferred_threshold_is_inferred(self):
        assert tier_from_confidence(0.4) == INFERRED

    def test_low_value_is_observed(self):
        assert tier_from_confidence(0.1) == OBSERVED

    def test_zero_is_observed(self):
        assert tier_from_confidence(0.0) == OBSERVED

    def test_none_treated_as_zero(self):
        assert tier_from_confidence(None) == OBSERVED


class TestLifeFactTier:
    def test_stated_fact_is_confirmed_regardless_of_confidence(self):
        """authority=2 (AUTHORITY_STATED) — David's own word — is confirmed
        by definition, even if its numeric confidence is low."""
        assert life_fact_tier(confidence=0.1, authority=2) == CONFIRMED

    def test_inferred_fact_reads_through_shared_thresholds(self):
        assert life_fact_tier(confidence=0.6, authority=1) == INFERRED
        assert life_fact_tier(confidence=0.2, authority=1) == OBSERVED
        assert life_fact_tier(confidence=0.9, authority=1) == CONFIRMED

    def test_none_authority_falls_back_to_numeric(self):
        assert life_fact_tier(confidence=0.9, authority=None) == CONFIRMED
