"""Shared silent-failure telemetry.

Fire-and-forget paths used to swallow exceptions at DEBUG (or not at all).
That made degraded state invisible: embeddings stopped generating, Neo4j
sync stopped catching up, observation inserts silently dropped — and
nobody noticed until retrieval quality cratered.

This module gives each subsystem a lightweight counter + rate-limited
WARNING so the operator actually sees when a fire-and-forget surface is
failing. Each ``Tracker`` instance owns one logical failure category.

Usage::

    _tracker = Tracker("pkg.embedding")

    try:
        await embed(...)
    except Exception as exc:
        _tracker.note(f"exception:{type(exc).__name__}")

The tracker logs once per LOG_INTERVAL_SEC so a broken service doesn't
flood the log, and exposes cumulative counts via ``get_stats()`` so debug
endpoints (``/debug/retrieval-funnel``) can surface the state.
"""

from __future__ import annotations

import logging
import time
from typing import Dict

logger = logging.getLogger(__name__)

# One WARNING per tracker per minute. Tune if noisy.
LOG_INTERVAL_SEC = 60.0


class Tracker:
    """Counts silent failures and emits a rate-limited WARNING.

    Thread-safe enough for our single-event-loop workload — counter
    updates are atomic under CPython; nothing needs a lock.
    """

    _registry: Dict[str, "Tracker"] = {}

    def __init__(self, name: str):
        self.name = name
        self._count = 0
        self._reasons: Dict[str, int] = {}
        self._last_logged = 0.0
        Tracker._registry[name] = self

    def note(self, reason: str = "unspecified") -> None:
        """Record one silent failure. Cheap — safe from hot paths."""
        self._count += 1
        self._reasons[reason] = self._reasons.get(reason, 0) + 1
        now = time.monotonic()
        if now - self._last_logged >= LOG_INTERVAL_SEC:
            self._last_logged = now
            top = sorted(self._reasons.items(), key=lambda kv: -kv[1])[:3]
            reasons_str = ", ".join(f"{r}={c}" for r, c in top)
            logger.warning(
                "%s degraded: %d silent failures so far (latest=%s). Top: %s",
                self.name, self._count, reason, reasons_str,
            )

    def reset(self) -> None:
        self._count = 0
        self._reasons.clear()
        self._last_logged = 0.0

    def stats(self) -> dict:
        return {
            "name": self.name,
            "count": self._count,
            "reasons": dict(self._reasons),
        }

    @classmethod
    def all_stats(cls) -> Dict[str, dict]:
        """All trackers' stats, for debug endpoints."""
        return {name: tr.stats() for name, tr in cls._registry.items()}
