"""
Silent-failure telemetry for fire-and-forget `except: pass` paths.

`swallow()` replaces a bare except that swallows an exception with no trace
of it happening. Logs at DEBUG (the exception isn't actionable in real
time — that's the whole point of swallowing it in the caller) and
increments a Redis counter so a call site that starts failing 100% of the
time shows up in aggregate instead of vanishing into a debug log nobody
tails. This is the early-warning system the periodic manual audits
currently provide months late (deaf Jetson, dark watch streams, empty
pattern tables were all silent swallows first).

Redis-backed and daily-bucketed — unlike the in-process
`silent_failure_tracker.Tracker` (rate-limited WARNING + in-memory stats,
already used by PKG/observation_log/deliberation_gate), counts here survive
a container restart and aggregate across the backend + several Celery
workers, and a chronic failure can't hide inside an all-time total that
never resets. Use `swallow()` for "is this call site healthy today";
`Tracker` where a rate-limited WARNING in the log is what's wanted.

Usage:
    from app.core.swallow import swallow

    try:
        await do_optional_thing()
    except Exception as exc:
        await swallow(logger, "chat_stream.chess_intercept", exc)

Migrate incrementally — each file converts its silent excepts the next
time it's touched (374+ sites exist; this is not a one-time sweep, same
rule as the tool-exception-logging hygiene pass).
"""
import logging
from datetime import datetime, timezone

from app.core.redis import get_redis

_KEY_PREFIX = "swallow"
_BUCKET_TTL_SECONDS = 14 * 86400  # daily buckets auto-expire after two weeks


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def swallow(logger: logging.Logger, site: str, exc: Exception) -> None:
    """Record a silently-swallowed exception at `site` — a short dotted
    name identifying the call site (e.g. "chat_stream.host_inspection").
    """
    logger.debug(f"[swallow:{site}] {type(exc).__name__}: {exc}")
    try:
        r = await get_redis()
        key = f"{_KEY_PREFIX}:{site}:{_today()}"
        await r.incr(key)
        await r.expire(key, _BUCKET_TTL_SECONDS)
    except Exception:
        pass  # telemetry must never break the caller's fire-and-forget path
