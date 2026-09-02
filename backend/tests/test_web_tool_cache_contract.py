"""Regression tests for the async SearchService cache contract."""

import asyncio
from unittest.mock import AsyncMock

from app.services.search_service import search_service
from app.tools.get_page_details import GetPageDetailsTool
from app.tools.get_web_search_details import GetWebSearchDetailsTool
from app.tools.open_page import OpenPageTool
from app.tools.web_search import WebSearchTool


def test_web_search_succeeds_when_detail_cache_is_unavailable(monkeypatch):
    provider_result = {
        "results": [
            {"title": "llama.cpp", "url": "https://example.test/llama", "snippet": "news"}
        ]
    }
    monkeypatch.setattr(search_service, "web_search", AsyncMock(return_value=provider_result))
    cache_write = AsyncMock(return_value=False)
    monkeypatch.setattr(search_service, "cache_set_json", cache_write)

    result = asyncio.run(WebSearchTool().execute("user", query="llama.cpp ngram"))

    assert result.success is True
    assert result.data["result_count"] == 1
    assert result.data["note"] == "Full-detail cache unavailable; summaries remain valid"
    cache_write.assert_awaited_once()


def test_web_search_reports_cached_detail_reference(monkeypatch):
    monkeypatch.setattr(search_service, "web_search", AsyncMock(return_value={"results": []}))
    cache_write = AsyncMock(return_value=True)
    monkeypatch.setattr(search_service, "cache_set_json", cache_write)

    result = asyncio.run(WebSearchTool().execute("user", query="test"))

    assert result.success is True
    assert "full details stored" in result.message
    assert result.data["reference_id"]


def test_open_page_succeeds_when_detail_cache_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        search_service,
        "open_page",
        AsyncMock(return_value={"title": "Example", "plain_text": "body"}),
    )
    monkeypatch.setattr(search_service, "cache_set_json", AsyncMock(return_value=False))

    result = asyncio.run(OpenPageTool().execute("user", url="https://example.test"))

    assert result.success is True
    assert result.data["title"] == "Example"
    assert result.data["note"] == "Full-detail cache unavailable; preview remains valid"


def test_search_detail_tool_uses_search_service_cache_helper(monkeypatch):
    cached = {
        "results": [{"url": "https://example.test/one", "title": "One"}]
    }
    cache_read = AsyncMock(return_value=cached)
    monkeypatch.setattr(search_service, "cache_get_json", cache_read)

    result = asyncio.run(
        GetWebSearchDetailsTool().execute("user", reference_id="search-ref")
    )

    assert result.success is True
    assert result.data == cached
    cache_read.assert_awaited_once_with("websearch_details:search-ref")


def test_page_detail_tool_uses_search_service_cache_helper(monkeypatch):
    cached = {"title": "Page", "plain_text": "full page"}
    cache_read = AsyncMock(return_value=cached)
    monkeypatch.setattr(search_service, "cache_get_json", cache_read)

    result = asyncio.run(
        GetPageDetailsTool().execute("user", reference_id="page-ref")
    )

    assert result.success is True
    assert "full page" in result.data["content"]
    assert "<untrusted" in result.data["content"]
    cache_read.assert_awaited_once_with("page_details:page-ref")


def test_detail_cache_miss_is_a_normal_tool_failure(monkeypatch):
    monkeypatch.setattr(search_service, "cache_get_json", AsyncMock(return_value=None))

    search_result = asyncio.run(
        GetWebSearchDetailsTool().execute("user", reference_id="expired")
    )
    page_result = asyncio.run(
        GetPageDetailsTool().execute("user", reference_id="expired")
    )

    assert search_result.success is False
    assert page_result.success is False
    assert "not found or expired" in search_result.message
    assert "not found or expired" in page_result.message
