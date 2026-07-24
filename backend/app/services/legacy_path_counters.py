"""
Legacy-vs-target path counters (SINGULAR_SARA_MASTER_PLAN §13/§C0).

"Add counters for each legacy and target path" — so a cutover decision is
backed by "this path actually gets used N times a day," not a guess, and the
later exit gates that depend on traffic ("Shadow comparisons show no lost
high-value notices," C12: "No legacy cognition... path receives traffic")
have a real number to check instead of an assertion.

Counters are Redis INCRs keyed by (path_name, legacy|target, UTC day) —
cheap enough to call from a hot path, self-expiring so this never becomes an
unbounded table, and readable as a simple sum over the last N days.

First real wiring (§C5's ambient-state consolidation): `kernel.ambient_turn`
records "target" for `ambient_cognition` on every call, while the two direct
`deliberation_engine.run()` call sites in `app/tasks/autonomy.py`
(`periodic_deliberation_fallback`, `deep_deliberation`) that still bypass the
kernel record "legacy" — making the exact fracture §3.2 describes
("Engaged, focused, and dreaming cognition are not yet kernel-owned")
measurable instead of anecdotal.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

logger = logging.getLogger(__name__)

_KEY_PREFIX = "singular:path_counter"
# ~5 weeks — outlives the plan's 4-continuous-week C12 cutover observation gate.
_TTL_SECONDS = 35 * 24 * 3600
_LANES = ("legacy", "target")


def _day_bucket(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


async def _get_redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


async def _record(path_name: str, lane: str) -> None:
    if lane not in _LANES:
        raise ValueError(f"lane must be one of {_LANES}, got {lane!r}")
    key = f"{_KEY_PREFIX}:{path_name}:{lane}:{_day_bucket(datetime.now(timezone.utc))}"
    try:
        r = await _get_redis()
        await r.incr(key)
        await r.expire(key, _TTL_SECONDS)
        try:
            await r.close()
        except Exception:
            pass
    except Exception as e:
        # Never let telemetry break the path it's measuring.
        logger.debug(f"[legacy_path_counters] record failed for {key}: {e}")


async def record_legacy_path(path_name: str) -> None:
    await _record(path_name, "legacy")


async def record_target_path(path_name: str) -> None:
    await _record(path_name, "target")


async def get_counts(path_name: str, days: int = 7) -> Dict[str, int]:
    """Sum legacy vs target counts for `path_name` over the last `days` UTC
    day-buckets (today inclusive)."""
    r = await _get_redis()
    legacy_total = 0
    target_total = 0
    try:
        today = datetime.now(timezone.utc)
        for i in range(days):
            day = _day_bucket(today - timedelta(days=i))
            legacy_val = await r.get(f"{_KEY_PREFIX}:{path_name}:legacy:{day}")
            target_val = await r.get(f"{_KEY_PREFIX}:{path_name}:target:{day}")
            legacy_total += int(legacy_val or 0)
            target_total += int(target_val or 0)
    finally:
        try:
            await r.close()
        except Exception:
            pass
    return {"path_name": path_name, "days": days, "legacy": legacy_total, "target": target_total}
