"""
gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 6: Flash-Next thinks by
default (--reasoning-effort xhigh) and burns the whole max_tokens budget on
reasoning prose when a background call doesn't turn it off — the entity
extractor's JSON never arrived. feedback_qwen_thinking.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.outbox_processor import OutboxProcessor


@pytest.mark.asyncio
async def test_llm_extract_entities_disables_thinking():
    processor = OutboxProcessor()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"people": [], "projects": [], "topics": []}'}}]
    }

    captured = {}

    async def _fake_post(url, json=None, **kwargs):
        captured["json"] = json
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = _fake_post
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        await processor._llm_extract_entities("some note content", "user-1")

    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["json"]["max_tokens"] == 400
