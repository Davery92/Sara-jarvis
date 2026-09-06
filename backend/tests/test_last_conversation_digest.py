"""
gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 7: a "Good morning!" turn
after a session close should carry the previous conversation's digest
forward instead of vector-recalling two other "good morning" episodes.
"""
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_digest_round_trips_through_redis():
    from app.services.unified_context import write_last_conversation_digest, read_last_conversation_digest

    user_id = "test-user-amnesia-digest"
    ended_at = datetime(2026, 9, 3, 21, 7, tzinfo=timezone.utc)
    await write_last_conversation_digest(user_id, "Walked the Salem waterfront, saw the magic show.", ended_at)

    digest = await read_last_conversation_digest(user_id)
    assert digest is not None
    assert "magic show" in digest["summary"]
    assert digest["ended_at"].startswith("2026-09-03")


@pytest.mark.asyncio
async def test_digest_is_truncated_to_600_chars():
    from app.services.unified_context import write_last_conversation_digest, read_last_conversation_digest

    user_id = "test-user-amnesia-digest-long"
    await write_last_conversation_digest(user_id, "x" * 5000, datetime.now(timezone.utc))
    digest = await read_last_conversation_digest(user_id)
    assert len(digest["summary"]) <= 600


@pytest.mark.asyncio
async def test_missing_digest_returns_none():
    from app.services.unified_context import read_last_conversation_digest
    digest = await read_last_conversation_digest("user-with-no-digest-ever-written")
    assert digest is None
