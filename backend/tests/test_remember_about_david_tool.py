"""
Tests for RememberAboutDavidTool's Arc 5.2 minter-ruling confidence cap.
This tool is LLM-self-assessed — Sara decides both whether to call it and
what confidence to claim, with no independent check that a "David said X"
interpretation was actually explicit. Real David statements get to
confirmed tier for real via the verification loop or promote_corroborated_
facts(), not by trusting the tool call's own confidence claim.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.personal_knowledge import RememberAboutDavidTool
from app.services.confidence_ladder import CONFIRMED_AT


@pytest.fixture
def tool():
    return RememberAboutDavidTool()


class TestConfidenceCap:
    @pytest.mark.asyncio
    async def test_requested_confidence_above_entry_tier_is_capped(self, tool):
        with patch("app.services.personal_knowledge_graph.personal_kg.upsert_fact",
                   return_value="pkg-1") as mock_upsert:
            result = await tool.execute(
                "user-1", fact_type="Preference", properties={"value": "tea"}, confidence=0.99
            )

        assert result.success is True
        used_confidence = mock_upsert.call_args.kwargs["confidence"]
        assert used_confidence < CONFIRMED_AT

    @pytest.mark.asyncio
    async def test_default_confidence_is_entry_tier(self, tool):
        with patch("app.services.personal_knowledge_graph.personal_kg.upsert_fact",
                   return_value="pkg-1") as mock_upsert:
            await tool.execute("user-1", fact_type="Preference", properties={"value": "tea"})

        used_confidence = mock_upsert.call_args.kwargs["confidence"]
        assert used_confidence < CONFIRMED_AT

    @pytest.mark.asyncio
    async def test_low_requested_confidence_is_left_alone(self, tool):
        with patch("app.services.personal_knowledge_graph.personal_kg.upsert_fact",
                   return_value="pkg-1") as mock_upsert:
            await tool.execute(
                "user-1", fact_type="Preference", properties={"value": "tea"}, confidence=0.3
            )

        used_confidence = mock_upsert.call_args.kwargs["confidence"]
        assert used_confidence == 0.3

    @pytest.mark.asyncio
    async def test_missing_properties_fails_without_calling_upsert(self, tool):
        with patch("app.services.personal_knowledge_graph.personal_kg.upsert_fact") as mock_upsert:
            result = await tool.execute("user-1", fact_type="Preference", properties={})

        assert result.success is False
        mock_upsert.assert_not_called()
