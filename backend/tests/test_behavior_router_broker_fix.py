"""
Regression test for BehaviorRouter.classify() (originally Arc 6.2 work-order
item 6, 2026-07-30; rewritten 2026-07-31).

History: `_get_model()`/`_get_llm_client()` originally read
settings.OPENAI_MODEL/OPENAI_BASE_URL (uppercase attributes that don't exist
on Settings), then were "fixed" to route through llm_broker's "utility"
capability -- but `_get_llm_client()` still built an `openai.AsyncOpenAI`
client, and `openai` was never an installed dependency in this codebase, so
every real call raised ModuleNotFoundError. The prior version of this test
suite knew that (its own docstring said so) and mocked `sys.modules["openai"]`
before importing, which is exactly why a real, live bug (confirmed 2026-07-31:
a real `route_behavior` tool call failed with `ModuleNotFoundError: No module
named 'openai'`) stayed green for a full day.

Fixed for real (2026-07-31): `classify()` now calls `resolve("utility")` +
a raw `httpx` POST directly -- no OpenAI-SDK-shaped client, no `openai`
import anywhere in this module. This test exercises that real path by
mocking `httpx.AsyncClient.post` (the actual transport), not the package
that used to be silently faked out from under it.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.behavior_router import BehaviorRouter, BehaviorDestination


@pytest.fixture
def router():
    return BehaviorRouter()


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "choices": [{"message": {"content": json.dumps(payload)}}]
    })
    return resp


class TestClassifyUsesBrokerAndHttpx:
    @pytest.mark.asyncio
    async def test_classify_resolves_utility_capability(self, router):
        """The real regression: classify() must ask the broker for the
        model/endpoint, not read a nonexistent Settings attribute or build
        an SDK client around a package that isn't installed."""
        classification = {
            "classification": "automation",
            "confidence": 0.9,
            "reasoning": "scheduled, deterministic action",
        }
        with patch(
            "app.services.llm_broker.resolve",
            return_value={"model": "qwen3.8-27b", "base_url": "http://x:8081/v1"},
        ) as mock_resolve, patch(
            "httpx.AsyncClient.post", new=AsyncMock(return_value=_fake_response(classification))
        ):
            result = await router.classify("Turn off the lights at 11pm")

        mock_resolve.assert_called_once_with("utility")
        assert result.destination == BehaviorDestination.AUTOMATION
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_classify_posts_to_resolved_base_url(self, router):
        """The POST must go to the broker-resolved host, not a hardcoded
        one -- proves this is genuinely capability-routed, not just
        happening to work against whatever default is configured today."""
        classification = {"classification": "soul", "confidence": 0.8, "reasoning": "identity change"}
        post_mock = AsyncMock(return_value=_fake_response(classification))
        with patch(
            "app.services.llm_broker.resolve",
            return_value={"model": "qwen3.8-27b", "base_url": "http://custom-host:9999/v1"},
        ), patch("httpx.AsyncClient.post", new=post_mock):
            await router.classify("Be more direct")

        called_url = post_mock.call_args.args[0]
        assert called_url == "http://custom-host:9999/v1/chat/completions"

    def test_no_openai_import_anywhere_in_module(self):
        """Regression guard for the actual root cause: this module must
        never import the `openai` package (not installed in this codebase,
        confirmed via `pip show openai`) -- checking real import statements
        (not any prose mention of "openai"/"AsyncOpenAI" -- this file's own
        docstrings legitimately reference them for history) is a cheap,
        permanent tripwire against the pattern coming back."""
        import ast
        import inspect
        import app.services.behavior_router as mod
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name == "openai" for a in node.names), "found `import openai`"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "openai", "found `from openai import ...`"
