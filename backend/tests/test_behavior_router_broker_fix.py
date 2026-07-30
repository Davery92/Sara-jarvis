"""
Regression test for a real bug found in the Arc 6.2 broker-migration audit
(work-order item 6, 2026-07-30): BehaviorRouter._get_model()/_get_llm_client()
read settings.OPENAI_MODEL / settings.OPENAI_BASE_URL (uppercase), which
don't exist on Settings (only lowercase openai_model/openai_base_url do) —
this path raised AttributeError every time it actually executed. Fixed and
migrated onto llm_broker's "utility" capability in the same move.
"""
from unittest.mock import patch

import pytest

from app.services.behavior_router import BehaviorRouter


@pytest.fixture
def router():
    return BehaviorRouter()


class TestGetModelUsesBroker:
    def test_get_model_no_longer_raises_attributeerror(self, router):
        """The actual regression: this used to crash with AttributeError."""
        with patch("app.services.llm_broker.resolve", return_value={"model": "qwen3.6-27b", "base_url": "http://x"}):
            model = router._get_model()
        assert model == "qwen3.6-27b"

    def test_get_model_reads_utility_capability(self, router):
        with patch("app.services.llm_broker.resolve") as mock_resolve:
            mock_resolve.return_value = {"model": "some-model", "base_url": "http://x"}
            router._get_model()
        mock_resolve.assert_called_once_with("utility")


class TestGetLlmClientUsesBroker:
    @pytest.mark.asyncio
    async def test_client_construction_reads_broker_base_url(self, router):
        """A SECOND real bug found alongside the attribute typo: the
        `openai` package isn't installed in this environment at all
        (confirmed via `pip show openai` — not in requirements.txt),
        so _get_llm_client() would also raise ModuleNotFoundError in
        practice. Out of scope to fix here (adding a dependency needs
        its own care/rebuild, not a same-diff fix) — flagged, not
        silently patched over. This test verifies the part that IS
        fixed (broker resolution feeds the client constructor
        correctly) without needing the actual package installed."""
        import sys
        import types
        fake_openai = types.ModuleType("openai")

        class _FakeAsyncOpenAI:
            def __init__(self, base_url=None, api_key=None):
                self.base_url = base_url
                self.api_key = api_key

        fake_openai.AsyncOpenAI = _FakeAsyncOpenAI
        with patch.dict(sys.modules, {"openai": fake_openai}), \
             patch("app.services.llm_broker.resolve", return_value={"model": "m", "base_url": "http://x:8081/v1"}):
            client = await router._get_llm_client()
        assert client.base_url == "http://x:8081/v1"
