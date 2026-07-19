"""Quiet mode / guest mode — the one-action kill switch (Phase 11E).

Suspends all *proactive* outreach and autonomous *home* actions for N hours (or
until turned off) WITHOUT stopping observation, logging, or reactive answers.
Guest mode additionally pauses pattern-learning (guests shouldn't train the
model of the house). Enforced in the deliberation GATE, not the prompt — a hard
gate the model cannot talk its way past.

Redis-backed so backend + celery share one truth; auto-expires by TTL.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_QUIET_KEY = "sara:quiet_mode"
_GUEST_KEY = "sara:guest_mode"


def _redis():
    import redis as _redis
    return _redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


def set_quiet(hours: Optional[float] = None, guest: bool = False) -> dict:
    """Enable quiet (or guest) mode. hours=None means 'until turned off' (30-day cap)."""
    ttl = int((hours or 720) * 3600)
    try:
        r = _redis()
        r.set(_QUIET_KEY, "1", ex=ttl)
        if guest:
            r.set(_GUEST_KEY, "1", ex=ttl)
        r.close()
        logger.info(f"[quiet_mode] enabled ({'guest' if guest else 'quiet'}), {hours or 'until off'}h")
        return {"quiet": True, "guest": guest, "hours": hours}
    except Exception as e:
        return {"error": str(e)}


def clear_quiet() -> dict:
    try:
        r = _redis()
        r.delete(_QUIET_KEY, _GUEST_KEY)
        r.close()
        logger.info("[quiet_mode] cleared")
        return {"quiet": False}
    except Exception as e:
        return {"error": str(e)}


def is_quiet() -> bool:
    try:
        r = _redis()
        v = r.exists(_QUIET_KEY)
        r.close()
        return bool(v)
    except Exception:
        return False  # fail-open to normal behavior


def is_guest() -> bool:
    try:
        r = _redis()
        v = r.exists(_GUEST_KEY)
        r.close()
        return bool(v)
    except Exception:
        return False


def status() -> dict:
    try:
        r = _redis()
        q = r.exists(_QUIET_KEY)
        g = r.exists(_GUEST_KEY)
        ttl = r.ttl(_QUIET_KEY) if q else None
        r.close()
        return {"quiet": bool(q), "guest": bool(g), "seconds_remaining": ttl if ttl and ttl > 0 else None}
    except Exception:
        return {"quiet": False, "guest": False}
