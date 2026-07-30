"""
Tests for verification_loop.py (Arc 5.2) — "the verification loop retires
unverified facts one natural question at a time (capped, anti-nag)." This
covers the "ask" half only: picking the fact, generating the question,
minting it through the existing say_candidate pipeline, capped at 1/day.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.verification_loop import (
    _pick_unverified_fact,
    generate_verification_candidate,
    verified_today,
)


class TestVerifiedToday:
    @pytest.mark.asyncio
    async def test_true_when_a_verification_candidate_exists_today(self):
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(first=lambda: (1,)))
        assert await verified_today(mock_db, "user-1") is True

    @pytest.mark.asyncio
    async def test_false_when_none_exists(self):
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(first=lambda: None))
        assert await verified_today(mock_db, "user-1") is False


class TestPickUnverifiedFact:
    def test_needs_review_flagged_fact_takes_priority(self):
        with patch("app.services.personal_knowledge_graph.personal_kg.get_needs_review",
                   return_value=[{"pkg_id": "p1", "fact_summary": "David likes tea now",
                                  "review_reason": "contradicts prior statement",
                                  "review_evidence": "said 'I switched to coffee' on 7/28"}]):
            fact = _pick_unverified_fact()

        assert fact["pkg_id"] == "p1"
        assert fact["reason"] == "contradicts prior statement"

    def test_falls_back_to_lowest_confidence_observed_tier_fact(self):
        with patch("app.services.personal_knowledge_graph.personal_kg.get_needs_review", return_value=[]), \
             patch("app.services.personal_knowledge_graph.personal_kg.browse", return_value=[
                 {"type": "Preference", "pkg_id": "p2", "value": "tea", "domain": "drink",
                  "strength": "like", "confidence": 0.3},
                 {"type": "Preference", "pkg_id": "p3", "value": "coffee", "domain": "drink",
                  "strength": "like", "confidence": 0.1},
                 {"type": "Preference", "pkg_id": "p4", "value": "juice", "domain": "drink",
                  "strength": "like", "confidence": 0.9},  # confirmed tier, must be excluded
             ]):
            fact = _pick_unverified_fact()

        assert fact["pkg_id"] == "p3"  # lowest confidence among observed-tier

    def test_no_flagged_and_no_low_confidence_facts_returns_none(self):
        with patch("app.services.personal_knowledge_graph.personal_kg.get_needs_review", return_value=[]), \
             patch("app.services.personal_knowledge_graph.personal_kg.browse", return_value=[
                 {"type": "Preference", "pkg_id": "p5", "value": "tea", "confidence": 0.9},
             ]):
            fact = _pick_unverified_fact()

        assert fact is None


class TestGenerateVerificationCandidate:
    @pytest.mark.asyncio
    async def test_skips_when_already_verified_today(self):
        mock_db = MagicMock()
        with patch("app.services.verification_loop.verified_today", new=AsyncMock(return_value=True)):
            result = await generate_verification_candidate(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_nothing_to_verify(self):
        mock_db = MagicMock()
        with patch("app.services.verification_loop.verified_today", new=AsyncMock(return_value=False)), \
             patch("app.services.verification_loop._pick_unverified_fact", return_value=None):
            result = await generate_verification_candidate(mock_db, "user-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_mints_candidate_with_dedupe_key_and_correct_kind(self):
        mock_db = MagicMock()
        fact = {"pkg_id": "p1", "fact_summary": "David likes tea now",
                "reason": "contradicts prior statement", "evidence": "said coffee on 7/28"}
        with patch("app.services.verification_loop.verified_today", new=AsyncMock(return_value=False)), \
             patch("app.services.verification_loop._pick_unverified_fact", return_value=fact), \
             patch("app.services.verification_loop._generate_question",
                   new=AsyncMock(return_value="Hey, are you still drinking mostly coffee, or has tea taken over?")), \
             patch("app.services.say_candidate.create_candidate", new=AsyncMock(return_value="cand-1")) as mock_create:
            result = await generate_verification_candidate(mock_db, "user-1")

        assert result == "Hey, are you still drinking mostly coffee, or has tea taken over?"
        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["kind"] == "inform"
        assert call_kwargs["source"] == "verification"
        assert call_kwargs["dedupe_key"] == "verify:pkg:p1"

    @pytest.mark.asyncio
    async def test_question_generation_failure_mints_nothing(self):
        mock_db = MagicMock()
        fact = {"pkg_id": "p1", "fact_summary": "David likes tea now",
                "reason": "contradicts prior statement", "evidence": ""}
        with patch("app.services.verification_loop.verified_today", new=AsyncMock(return_value=False)), \
             patch("app.services.verification_loop._pick_unverified_fact", return_value=fact), \
             patch("app.services.verification_loop._generate_question", new=AsyncMock(return_value=None)), \
             patch("app.services.say_candidate.create_candidate", new=AsyncMock()) as mock_create:
            result = await generate_verification_candidate(mock_db, "user-1")

        assert result is None
        mock_create.assert_not_awaited()
