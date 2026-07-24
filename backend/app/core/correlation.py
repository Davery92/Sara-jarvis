"""
Correlation IDs (SINGULAR_SARA_MASTER_PLAN §C0/§C1).

"Add correlation IDs spanning event, kernel turn, intent, mission, action,
outbound intent, and delivery." Today those six concepts live in separate
tables/logs with no shared key, so tracing "why did Sara do that" means
manually cross-referencing timestamps. This module is the one place that
mints and carries those IDs.

Deliberately minimal: a stable ID shape (`CorrelationIds`) plus a contextvar
so a kernel turn can mint one ID at its entry point and have it flow through
whatever it calls in the same async chain, without every callee needing the
ID threaded through its signature. Nothing reads or requires these IDs yet —
wiring them into kernel.py first (§13 item 2) makes them observable before
anything downstream depends on them.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional


def new_id(prefix: str = "") -> str:
    """A short, stable, greppable correlation ID."""
    raw = uuid.uuid4().hex[:16]
    return f"{prefix}_{raw}" if prefix else raw


@dataclass
class CorrelationIds:
    """The correlation spine for one causal chain. Any field may be absent —
    e.g. an ambient kernel turn has a kernel_turn_id but no action_id until it
    decides to act."""
    event_id: Optional[str] = None
    kernel_turn_id: Optional[str] = None
    intent_id: Optional[str] = None
    mission_id: Optional[str] = None
    action_id: Optional[str] = None
    outbound_intent_id: Optional[str] = None
    delivery_id: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "event_id": self.event_id,
            "kernel_turn_id": self.kernel_turn_id,
            "intent_id": self.intent_id,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "outbound_intent_id": self.outbound_intent_id,
            "delivery_id": self.delivery_id,
        }
        return {k: v for k, v in out.items() if v is not None}


_current: ContextVar[Optional[CorrelationIds]] = ContextVar("_singular_correlation", default=None)


def bind_correlation(ids: CorrelationIds) -> None:
    """Bind correlation IDs for the remainder of the current async context."""
    _current.set(ids)


def get_current_correlation() -> CorrelationIds:
    """Return the bound correlation IDs, or an empty set if nothing is bound
    (e.g. code running outside a kernel turn)."""
    return _current.get() or CorrelationIds()
