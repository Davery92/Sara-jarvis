"""
Tests for llm_broker.get_broker_client() (Arc 6.2, work-order item 6):
resolve() existed but nothing outside the two admin settings endpoints ever
called it -- this is the client-factory layer that lets real callers migrate
onto capability classes instead of reading openai_model directly.
"""
import sys
import types
from unittest.mock import patch

import pytest

from app.services.llm_broker import get_broker_client


def _fake_openai_module():
    fake_openai = types.ModuleType("openai")

    class _FakeAsyncOpenAI:
        def __init__(self, base_url=None, api_key=None):
            self.base_url = base_url
            self.api_key = api_key

    fake_openai.AsyncOpenAI = _FakeAsyncOpenAI
    return fake_openai


class TestGetBrokerClient:
    @pytest.mark.asyncio
    async def test_returns_client_and_model_for_resolved_capability(self):
        with patch.dict(sys.modules, {"openai": _fake_openai_module()}), \
             patch(
                 "app.services.llm_broker.resolve",
                 return_value={"model": "qwen3.6-27b", "base_url": "http://100.104.68.115:8081/v1"},
             ) as mock_resolve:
            client, model = await get_broker_client("utility")

        mock_resolve.assert_called_once_with("utility")
        assert model == "qwen3.6-27b"
        assert client.base_url == "http://100.104.68.115:8081/v1"

    @pytest.mark.asyncio
    async def test_falls_back_to_not_needed_api_key_when_unset(self):
        with patch.dict(sys.modules, {"openai": _fake_openai_module()}), \
             patch(
                 "app.services.llm_broker.resolve",
                 return_value={"model": "m", "base_url": "http://x"},
             ), \
             patch("app.core.config.settings") as mock_settings:
            del mock_settings.openai_api_key
            mock_settings.openai_api_key = ""
            client, _ = await get_broker_client("utility")

        assert client.api_key == "not-needed"

    @pytest.mark.asyncio
    async def test_unknown_capability_propagates_valueerror(self):
        with pytest.raises(ValueError):
            await get_broker_client("not-a-real-capability")
