"""Retrieval funnel observability.

A lightweight in-memory ring buffer that every retrieval path can call to
report what it did: which source, how long, how many rows came back, and
whether anything failed. Exposed via ``/debug/retrieval-funnel`` so we can
tell at a glance when a subsystem is quietly returning zero results.

Design choices (single-user tool, so we can be simple):
  * Module-level ring buffer (collections.deque). No Redis, no DB.
  * Bounded to RING_SIZE events — oldest evicted as new events arrive.
  * Thread-safe under asyncio because deque append/popleft are atomic in
    CPython; we don't need a lock for this workload.
  * Per-source aggregate counters so we can show rates over the whole
    uptime without replaying every recorded event.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Dict, Optional

# Soft cap — plenty of headroom for a few days of inspection without
# turning into a memory leak. Tune if the deque ever shows up in profiles.
RING_SIZE = 500


@dataclass
class RetrievalEvent:
    """One retrieval call's worth of metadata."""

    source: str                 # "episodes", "notes", "documents", "hydra.fusion", etc.
    query: str                  # Truncated — full text is not useful here
    result_count: int           # Rows returned
    latency_ms: float           # Wall-clock
    monotonic_ts: float         # time.monotonic() at completion
    degraded: bool = False      # True if we fell back (e.g. recency-only)
    error: Optional[str] = None  # Exception class name, if any
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_events: Deque[RetrievalEvent] = deque(maxlen=RING_SIZE)

# Per-source cumulative counters — survive beyond the ring buffer so we
# can still say "episode retrieval has had 3,142 calls, 47 errors" even
# when the individual events have rolled off.
_aggregates: Dict[str, Dict[str, float]] = {}


def _agg(source: str) -> Dict[str, float]:
    a = _aggregates.get(source)
    if a is None:
        a = {
            "calls": 0,
            "errors": 0,
            "degraded": 0,
            "empty": 0,
            "total_latency_ms": 0.0,
            "total_results": 0,
        }
        _aggregates[source] = a
    return a


def record(
    source: str,
    query: str,
    result_count: int,
    latency_ms: float,
    *,
    degraded: bool = False,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one retrieval call. Cheap — safe to call from hot paths."""
    event = RetrievalEvent(
        source=source,
        query=(query or "")[:200],
        result_count=int(result_count or 0),
        latency_ms=round(float(latency_ms or 0.0), 2),
        monotonic_ts=time.monotonic(),
        degraded=bool(degraded),
        error=error,
        metadata=dict(metadata or {}),
    )
    _events.append(event)

    a = _agg(source)
    a["calls"] += 1
    a["total_latency_ms"] += event.latency_ms
    a["total_results"] += event.result_count
    if error:
        a["errors"] += 1
    if degraded:
        a["degraded"] += 1
    if event.result_count == 0 and error is None:
        a["empty"] += 1


class observe:
    """Async context manager that records a retrieval call on exit.

    Usage::

        async with observe("episodes", query) as ev:
            rows = await fetch(...)
            ev.result_count = len(rows)
            # ev.degraded = True  # if you fell back
            # ev.metadata["note"] = "..."  # optional
    """

    def __init__(self, source: str, query: str, **metadata: Any) -> None:
        self.source = source
        self.query = query
        self.result_count = 0
        self.degraded = False
        self.metadata: Dict[str, Any] = dict(metadata)
        self._start: float = 0.0
        self._error: Optional[str] = None

    async def __aenter__(self) -> "observe":
        self._start = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        latency_ms = (time.monotonic() - self._start) * 1000.0
        if exc_type is not None:
            self._error = exc_type.__name__
        record(
            self.source,
            self.query,
            self.result_count,
            latency_ms,
            degraded=self.degraded,
            error=self._error,
            metadata=self.metadata,
        )
        # Do not swallow the exception.
        return False


def snapshot(limit: int = 100) -> Dict[str, Any]:
    """Serializable snapshot of the funnel for the debug endpoint."""
    recent = list(_events)[-limit:]
    agg_view: Dict[str, Dict[str, Any]] = {}
    for source, a in sorted(_aggregates.items()):
        calls = a["calls"] or 0
        agg_view[source] = {
            "calls": int(calls),
            "errors": int(a["errors"]),
            "degraded": int(a["degraded"]),
            "empty": int(a["empty"]),
            "avg_latency_ms": round(a["total_latency_ms"] / calls, 2) if calls else 0.0,
            "avg_results": round(a["total_results"] / calls, 2) if calls else 0.0,
            "error_rate": round(a["errors"] / calls, 3) if calls else 0.0,
            "empty_rate": round(a["empty"] / calls, 3) if calls else 0.0,
        }

    return {
        "ring_size": RING_SIZE,
        "events_buffered": len(_events),
        "aggregates": agg_view,
        "recent": [e.to_dict() for e in reversed(recent)],
    }


def reset() -> None:
    """Test hook — wipe the buffer and aggregates."""
    _events.clear()
    _aggregates.clear()
