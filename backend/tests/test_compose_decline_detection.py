"""
Tests for compose_utterance()'s decline detection (work-order item 5, kill-
rate audit finding, 2026-07-30). Reading real composed_utterance kill
reasons found ~18% (4/22) were the model narrating its own decision not to
send ("Not sending this...", "The rain candidate was stale, so I'm sending
silence.", "Nothing to report — the pipeline is clear.") instead of the
canonical "Silence." the existing detection looked for — review correctly
killed these, but a real LLM call and a fake-looking utterance row were
wasted composing them. Prompt now explicitly asks for "Silence."; this is
the defensive backstop in case the model still doesn't comply.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.compose import ComposeDeclined, compose_utterance


def _llm_response(text: str) -> dict:
    import json
    return {"choices": [{"message": {"content": json.dumps({
        "text": text, "refs": [], "urgency": "normal",
    })}}]}


CANDIDATE = {"id": "c1", "kind": "inform", "summary": "s", "evidence": [], "judge_reason": "r"}


class TestDeclineNarrationBackstop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("meta_text", [
        "Not sending this. David already logged his Barbell Row session 7 hours ago.",
        "The rain candidate was stale, so I'm sending silence.",
        "Nothing to report — the pipeline is clear.",
        "The rain candidate was stale — it's 8:45 PM, so 'this afternoon' is already history. I'm keeping it quiet.",
    ])
    async def test_real_meta_commentary_examples_are_declined(self, meta_text):
        with patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=_llm_response(meta_text))
            mock_get_client.return_value = mock_client

            with pytest.raises(ComposeDeclined):
                await compose_utterance(CANDIDATE, "brief", [])

    @pytest.mark.asyncio
    async def test_canonical_silence_still_declined(self):
        with patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=_llm_response("Silence."))
            mock_get_client.return_value = mock_client

            with pytest.raises(ComposeDeclined):
                await compose_utterance(CANDIDATE, "brief", [])

    @pytest.mark.asyncio
    async def test_legitimate_message_mentioning_candidate_is_not_declined(self):
        """The word 'candidate' alone (e.g. a job candidate) must not
        false-positive against the decline-narration pattern."""
        text = "Not a big deal, but your candidate for the Risk Ninja role emailed back with questions."
        with patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=_llm_response(text))
            mock_get_client.return_value = mock_client

            result = await compose_utterance(CANDIDATE, "brief", [])
        assert result["text"] == text

    @pytest.mark.asyncio
    async def test_normal_real_message_is_composed_normally(self):
        text = "Got an email from Matt Albano about Derek Weippert tied to your 2:30 PM call."
        with patch("app.core.llm.get_background_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat_completion = AsyncMock(return_value=_llm_response(text))
            mock_get_client.return_value = mock_client

            result = await compose_utterance(CANDIDATE, "brief", [])
        assert result["text"] == text
