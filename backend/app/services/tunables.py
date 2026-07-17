"""
Tunables — read-side accessor for `tunable_setting` table.

Subsystems call `get_tunable("notification.cooldown.checkin_hours", default=2.0)`
to get the current value. Results are cached in-process for ~60 seconds so this
is cheap to call from hot paths. The cache is invalidated whenever the API
updates a tunable.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {}
_CACHE_LOADED_AT: float = 0.0
_CACHE_TTL_SEC: float = 60.0
_LOCK = threading.Lock()


def _reload_cache() -> None:
    global _CACHE, _CACHE_LOADED_AT
    try:
        from app.db.base import SessionLocal
        from app.models.tunable_setting import TunableSetting

        new_cache: Dict[str, Any] = {}
        with SessionLocal() as db:
            for row in db.query(TunableSetting).all():
                new_cache[row.key] = row.value
        _CACHE = new_cache
        _CACHE_LOADED_AT = time.time()
    except Exception as e:
        logger.warning("tunables: cache reload failed: %s", e)


def get_tunable(key: str, default: Any = None) -> Any:
    """Return the current value of `key`, or `default` if missing.

    Cache-first; reloads from DB at most once every ~60 seconds. Safe to
    call from sync or async code (no I/O on cache hit).
    """
    if (time.time() - _CACHE_LOADED_AT) > _CACHE_TTL_SEC:
        with _LOCK:
            if (time.time() - _CACHE_LOADED_AT) > _CACHE_TTL_SEC:
                _reload_cache()
    return _CACHE.get(key, default)


def get_tunable_int(key: str, default: int) -> int:
    v = get_tunable(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_tunable_float(key: str, default: float) -> float:
    v = get_tunable(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def get_tunable_str(key: str, default: str) -> str:
    v = get_tunable(key, default)
    return str(v) if v is not None else default


def get_tunable_bool(key: str, default: bool) -> bool:
    v = get_tunable(key, default)
    if isinstance(v, bool):
        return v
    s = str(v).strip().strip('"').lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def invalidate_cache() -> None:
    """Force the next get_tunable() call to refresh from DB. Called by the API on PATCH."""
    global _CACHE_LOADED_AT
    _CACHE_LOADED_AT = 0.0
