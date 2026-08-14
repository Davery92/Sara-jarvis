"""
Tests for app/core/redis.py — the shared Redis pool (B1,
docs/plans/HYGIENE_AND_STALE_CONTEXT_FIX_PLAN_2026_08_12.md).

Before this, every caller did `redis.asyncio.from_url(...)` fresh on each
use (59 call sites). The shared client here must (a) actually be shared
across calls on the same event loop, and (b) recycle itself when the loop
changes, since this backend runs across several independent loops (uvicorn,
and one per Celery task) and aioredis connections are loop-bound.
"""
import asyncio

import pytest

from app.core import redis as core_redis


@pytest.fixture(autouse=True)
def _reset_pool_state():
    """Each test starts from a clean slate — the module-level pool/loop-ref
    globals must not leak between tests."""
    core_redis._pool = None
    core_redis._pool_loop_ref = None
    core_redis._bytes_pool = None
    core_redis._bytes_pool_loop_ref = None
    yield
    core_redis._pool = None
    core_redis._pool_loop_ref = None
    core_redis._bytes_pool = None
    core_redis._bytes_pool_loop_ref = None


class TestGetRedisSharing:
    @pytest.mark.asyncio
    async def test_same_loop_returns_same_client(self):
        r1 = await core_redis.get_redis()
        r2 = await core_redis.get_redis()
        assert r1 is r2

    @pytest.mark.asyncio
    async def test_decoded_and_bytes_pools_are_distinct_clients(self):
        r_decoded = await core_redis.get_redis()
        r_bytes = await core_redis.get_redis_bytes()
        assert r_decoded is not r_bytes


class TestGetRedisLoopRecycling:
    def test_client_recreated_across_different_event_loops(self):
        """Simulates the FastAPI-loop vs Celery-task-loop scenario: a
        client acquired on one loop must not be silently reused on another."""
        seen = []

        async def _acquire():
            seen.append(await core_redis.get_redis())

        asyncio.run(_acquire())
        asyncio.run(_acquire())  # asyncio.run() spins up a brand-new loop each time

        assert seen[0] is not seen[1]
