"""
Tests for the batch digest hybrid (work-order item 12, 2026-07-30, David's
ruling): 3+ batch-origin candidates in a compose cycle become ONE digest
utterance; 1-2 still compose individually.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.compose import _partition_batch_groups
from app.services.compose import compose_digest_utterance, ComposeDeclined


def _row(id_, judge_reason, summary="s", kind="inform", evidence=None):
    return SimpleNamespace(id=id_, kind=kind, summary=summary, evidence=evidence or [], judge_reason=judge_reason)


class TestPartitionBatchGroups:
    def test_non_batch_rows_are_individual(self):
        rows = [_row(1, None), _row(2, "some other reason")]
        individual, groups = _partition_batch_groups(rows)
        assert len(individual) == 2
        assert groups == {}

    def test_two_batch_rows_stay_individual_below_threshold(self):
        rows = [_row(1, "[slot=morning] a"), _row(2, "[slot=morning] b")]
        individual, groups = _partition_batch_groups(rows)
        assert len(individual) == 2
        assert groups == {}

    def test_three_batch_rows_form_a_digest_group(self):
        rows = [_row(1, "[slot=morning] a"), _row(2, "[slot=morning] b"), _row(3, "[slot=morning] c")]
        individual, groups = _partition_batch_groups(rows)
        assert individual == []
        assert set(groups.keys()) == {"morning"}
        assert len(groups["morning"]) == 3

    def test_morning_and_evening_grouped_separately(self):
        rows = [
            _row(1, "[slot=morning] a"), _row(2, "[slot=morning] b"), _row(3, "[slot=morning] c"),
            _row(4, "[slot=evening] d"), _row(5, "[slot=evening] e"),
        ]
        individual, groups = _partition_batch_groups(rows)
        assert set(groups.keys()) == {"morning"}
        assert len(groups["morning"]) == 3
        # evening only has 2 -> falls back to individual
        assert len(individual) == 2

    def test_mixed_batch_and_direct_send_now(self):
        rows = [
            _row(1, "[slot=morning] a"), _row(2, "[slot=morning] b"), _row(3, "[slot=morning] c"),
            _row(4, None),  # a genuine direct send_now, never batched
        ]
        individual, groups = _partition_batch_groups(rows)
        assert len(individual) == 1
        assert individual[0].id == 4
        assert len(groups["morning"]) == 3

    def test_empty_judge_reason_is_individual_not_crash(self):
        rows = [_row(1, "")]
        individual, groups = _partition_batch_groups(rows)
        assert len(individual) == 1
        assert groups == {}


class TestComposeDigestUtterance:
    @pytest.mark.asyncio
    async def test_requires_at_least_two_candidates(self):
        with pytest.raises(ValueError):
            await compose_digest_utterance([{"kind": "inform", "summary": "x", "evidence": [], "judge_reason": ""}], "brief")

    @pytest.mark.asyncio
    async def test_composes_one_utterance_from_several_candidates(self):
        candidates = [
            {"kind": "inform", "summary": "email from Jim", "evidence": [], "judge_reason": "[slot=morning]"},
            {"kind": "inform", "summary": "calendar shift", "evidence": [], "judge_reason": "[slot=morning]"},
            {"kind": "inform", "summary": "goal milestone", "evidence": [], "judge_reason": "[slot=morning]"},
        ]
        fake_response = {
            "choices": [{"message": {"content":
                '{"text": "A few things: Jim emailed, your afternoon shifted, and you hit a goal milestone.", '
                '"refs": ["jim"], "urgency": "normal"}'
            }}]
        }
        with patch("app.services.compose._read_affect", new=AsyncMock(return_value=None)), \
             patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=fake_response)
            mock_get_client.return_value = mock_client
            result = await compose_digest_utterance(candidates, "brief text")
        assert "Jim" in result["text"]
        assert result["urgency"] == "normal"

    @pytest.mark.asyncio
    async def test_silence_raises_compose_declined(self):
        candidates = [
            {"kind": "inform", "summary": "a", "evidence": [], "judge_reason": ""},
            {"kind": "inform", "summary": "b", "evidence": [], "judge_reason": ""},
        ]
        fake_response = {"choices": [{"message": {"content": '{"text": "Silence.", "refs": [], "urgency": "normal"}'}}]}
        with patch("app.services.compose._read_affect", new=AsyncMock(return_value=None)), \
             patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=fake_response)
            mock_get_client.return_value = mock_client
            with pytest.raises(ComposeDeclined):
                await compose_digest_utterance(candidates, "brief text")


class TestDigestPromptShape:
    def test_prompt_forbids_bulleted_concatenation(self):
        from app.services.compose import _build_digest_prompt
        candidates = [
            {"kind": "inform", "summary": "a", "evidence": [], "judge_reason": ""},
            {"kind": "inform", "summary": "b", "evidence": [], "judge_reason": ""},
        ]
        sys_msg, user_msg = _build_digest_prompt(candidates, "brief", "voice doc")
        assert "NOT a bulleted list" in sys_msg
        assert "ONE flowing, coherent paragraph" in sys_msg
        assert "Item 1" in user_msg
        assert "Item 2" in user_msg
