"""
Shared Redis connection pool.

Every other module used to call `redis.asyncio.from_url(...)` fresh on each
use (59 call sites across 34 files) — no pooling reuse, so each one paid
full connection setup on every call. This is the one shared client those
call sites should import instead.

Loop-scoped, not process-scoped: aioredis connections are bound to the
asyncio event loop that created them, and this backend runs across several
independent loops (uvicorn's, and one per Celery task via `_run_async()`-
style helpers). A naive module-level singleton created once at import time
would work in FastAPI and then silently break/hang the first time a Celery
task tried to reuse it on a different loop.

Identity is tracked via a WEAKREF to the loop, not id(loop): CPython reuses
the id() of a freed object, so a new asyncio.run() loop can land on the
same id() a previous (now-closed) loop had — an id()-only guard then thinks
"same loop", hands out a client bound to a closed loop, and every call on
it hangs or raises "Future attached to a different loop". This is the same
bug class app/db/session.py's get_async_session_factory() already
documented and fixed; the fix here mirrors it.

Two flavors: `get_redis()` (decode_responses=True — the common case,
matches ~47 of the 59 original call sites) and `get_redis_bytes()`
(decode_responses=False, for the ~12 sites that store/read raw or pickled
bytes). Each needs its own connection pool — decode_responses is baked into
a pool's connection_kwargs at creation, so one pool can't serve both.

Callers should NOT call `.close()`/`.aclose()` on the client this returns —
it's shared and long-lived, closed only when the loop it belongs to changes.
"""
import asyncio
import os
import weakref
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_MAX_CONNECTIONS = 20

_pool: Optional[aioredis.Redis] = None
_pool_loop_ref: Optional["weakref.ref"] = None
_bytes_pool: Optional[aioredis.Redis] = None
_bytes_pool_loop_ref: Optional["weakref.ref"] = None


def _is_stale(client: Optional[aioredis.Redis], loop_ref: Optional["weakref.ref"], cur_loop) -> bool:
    if client is None:
        return True
    cached_loop = loop_ref() if loop_ref is not None else None
    if cached_loop is not cur_loop:
        return True  # different loop, or cached one was GC'd/closed underneath us
    return cached_loop.is_closed()


async def get_redis() -> aioredis.Redis:
    """Shared decode_responses=True client — strings in, strings out."""
    global _pool, _pool_loop_ref
    cur_loop = asyncio.get_running_loop()
    if _is_stale(_pool, _pool_loop_ref, cur_loop):
        if _pool is not None:
            try:
                await _pool.close()
            except Exception:
                pass
        _pool = aioredis.from_url(REDIS_URL, decode_responses=True, max_connections=_MAX_CONNECTIONS)
        _pool_loop_ref = weakref.ref(cur_loop)
    return _pool


async def get_redis_bytes() -> aioredis.Redis:
    """Shared raw-bytes client, for callers storing pickled/binary payloads."""
    global _bytes_pool, _bytes_pool_loop_ref
    cur_loop = asyncio.get_running_loop()
    if _is_stale(_bytes_pool, _bytes_pool_loop_ref, cur_loop):
        if _bytes_pool is not None:
            try:
                await _bytes_pool.close()
            except Exception:
                pass
        _bytes_pool = aioredis.from_url(REDIS_URL, decode_responses=False, max_connections=_MAX_CONNECTIONS)
        _bytes_pool_loop_ref = weakref.ref(cur_loop)
    return _bytes_pool
