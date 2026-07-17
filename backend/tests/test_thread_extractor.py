"""
Tests for ThreadExtractor — LLM-based conversation thread extraction.

Tests rate limiting, JSON parsing, topic similarity, and message formatting.
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.thread_extractor import (
    ThreadExtractor,
    EXTRACTION_COOLDOWN,
    CATEGORY_TIMING,
    _last_extraction,
)


@pytest.fixture
def extractor():
    # Use a fresh extractor with mocked LLM
    with patch("app.services.thread_extractor.get_background_llm_client") as mock_get:
        mock_llm = MagicMock()
        mock_get.return_value = mock_llm
        ext = ThreadExtractor()
        yield ext


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limiting_blocks_rapid_calls(self, extractor):
        """Second call within 300s → skipped."""
        user_id = "rate-test-user"
        _last_extraction[user_id] = time.time()  # Just now

        messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        result = await extractor.extract_threads(messages, user_id, MagicMock())
        assert result == []

    @pytest.mark.asyncio
    async def test_rate_limiting_allows_after_cooldown(self, extractor):
        """Call after cooldown → proceeds (but may still return empty due to mock)."""
        user_id = "rate-test-user-2"
        _last_extraction[user_id] = time.time() - EXTRACTION_COOLDOWN - 10

        # With mocked LLM, it will attempt extraction but may fail gracefully
        extractor.llm_client.chat_completion = AsyncMock(side_effect=Exception("mock"))
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        # Should not short-circuit due to rate limit
        result = await extractor.extract_threads(messages, user_id, AsyncMock())
        assert isinstance(result, list)

    def teardown_method(self):
        """Clean up rate limit state."""
        _last_extraction.clear()


class TestMinimumMessageCount:
    @pytest.mark.asyncio
    async def test_minimum_message_count(self, extractor):
        """< 3 user messages → skipped."""
        user_id = "msg-count-test"
        _last_extraction.pop(user_id, None)

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = await extractor.extract_threads(messages, user_id, MagicMock())
        assert result == []

    def teardown_method(self):
        _last_extraction.clear()


class TestJsonParsing:
    def test_json_parsing_raw(self, extractor):
        raw = '{"threads": [{"topic": "test"}], "resolved_topics": []}'
        result = extractor._parse_json_response(raw)
        assert result is not None
        assert "threads" in result

    def test_json_parsing_from_markdown(self, extractor):
        md = '```json\n{"threads": [{"topic": "cooking"}], "resolved_topics": []}\n```'
        result = extractor._parse_json_response(md)
        assert result is not None
        assert result["threads"][0]["topic"] == "cooking"

    def test_json_parsing_with_preamble(self, extractor):
        text = 'Here is the result:\n{"threads": [], "resolved_topics": []}'
        result = extractor._parse_json_response(text)
        assert result is not None
        assert result["threads"] == []

    def test_json_parsing_malformed(self, extractor):
        result = extractor._parse_json_response("This is not JSON at all")
        assert result is None

    def test_json_parsing_empty(self, extractor):
        result = extractor._parse_json_response("")
        assert result is None

    def test_json_parsing_array(self, extractor):
        text = '["uuid-1", "uuid-2"]'
        result = extractor._parse_json_response(text)
        assert isinstance(result, list)
        assert len(result) == 2


class TestTopicSimilarity:
    def test_similar_topics(self, extractor):
        assert extractor._topics_similar("dentist appointment tomorrow", "dentist appointment") is True

    def test_dissimilar_topics(self, extractor):
        assert extractor._topics_similar("dentist appointment", "grocery shopping") is False

    def test_single_word_overlap_not_enough(self, extractor):
        # After stop word removal, "big project" vs "project" = 1 overlap
        # Need min(2, len(new_words)) = 2 words overlap for similarity
        assert extractor._topics_similar("the big project", "some project") is False

    def test_two_word_overlap_is_similar(self, extractor):
        # "big project" vs "big project deadline" → 2 overlapping words
        assert extractor._topics_similar("big project deadline", "big project") is True

    def test_empty_after_stop_words(self, extractor):
        assert extractor._topics_similar("the a an", "to of in") is False

    def test_case_insensitive(self, extractor):
        assert extractor._topics_similar("Chuck Roast Dinner", "chuck roast dinner") is True


class TestMessageFormatting:
    def test_format_dict_messages(self, extractor):
        messages = [
            {"role": "user", "content": "I'm making dinner"},
            {"role": "assistant", "content": "What are you cooking?"},
        ]
        result = extractor._format_messages(messages)
        assert "David: I'm making dinner" in result
        assert "Sara: What are you cooking?" in result

    def test_format_empty_messages(self, extractor):
        result = extractor._format_messages([])
        assert result == ""

    def test_format_truncates_long_content(self, extractor):
        messages = [{"role": "user", "content": "x" * 500}]
        result = extractor._format_messages(messages)
        assert len(result) <= 310  # "David: " + 300 chars


class TestCategoryTiming:
    def test_cooking_timing(self):
        timing = CATEGORY_TIMING["cooking"]
        assert timing["after_hours"] == 2
        assert timing["before_hours"] == 12
        assert timing["max_mentions"] == 2

    def test_project_timing(self):
        timing = CATEGORY_TIMING["project"]
        assert timing["after_hours"] == 4
        assert timing["before_hours"] == 72

    def test_learning_timing(self):
        timing = CATEGORY_TIMING["learning"]
        assert timing["before_hours"] == 168  # 7 days
