"""A logging handler that buffers WARNING+ records to redis for Sara's
system_event ring buffer (Phase 2 interoception).

Design: the handler is sync and may fire in hot paths, so it must never do a DB
write or block on the network. It does a single fast redis LPUSH (capped list),
and a Celery beat task (`drain_system_events`) periodically moves buffered
records into the system_event table. If redis is unavailable it drops the record
silently — diagnostics are best-effort and must never break the app.
"""
from __future__ import annotations

import json
import logging
import os

_REDIS_KEY = "sara:system_events"
_MAX_BUFFER = 5000

# Loggers to never capture (avoid recursion / noise).
_SKIP_LOGGERS = (
    "app.core.diagnostics_logging",
    "app.services.diagnostics_service",
    "redis", "urllib3", "httpx", "httpcore",
)


class RedisBufferingHandler(logging.Handler):
    def __init__(self, service_name: str = "backend"):
        super().__init__(level=logging.WARNING)
        self.service_name = service_name
        self._redis = None

    def _client(self):
        if self._redis is None:
            import redis as _redis
            self._redis = _redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
        return self._redis

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                return
            if any(record.name.startswith(s) for s in _SKIP_LOGGERS):
                return
            tb = None
            if record.exc_info:
                try:
                    tb = self.format(record)
                except Exception:
                    tb = None
            payload = {
                "service": record.name,
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage()[:4000],
                "traceback": tb[:8000] if tb else None,
                "process": self.service_name,
                "ts": record.created,
            }
            r = self._client()
            pipe = r.pipeline()
            pipe.lpush(_REDIS_KEY, json.dumps(payload))
            pipe.ltrim(_REDIS_KEY, 0, _MAX_BUFFER - 1)
            pipe.execute()
        except Exception:
            # Diagnostics must never break the app.
            pass


def install(service_name: str = "backend") -> None:
    """Attach the buffering handler to the root logger (idempotent)."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, RedisBufferingHandler):
            return
    root.addHandler(RedisBufferingHandler(service_name=service_name))
