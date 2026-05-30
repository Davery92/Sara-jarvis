"""Trigger ABC + registry.

A trigger is a small detector. It reads existing tables/observation streams
and returns a TriggerContext when it sees something worth narrating, or
None otherwise. The coordinator handles everything else (cooldowns, LLM,
delivery).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


Severity = Literal[
    "roast",
    "observation",
    "achievement",
    "patch_note",
    "sponsored",
    "grudging",
    "deflected",
]


@dataclass
class TriggerContext:
    """What a trigger hands to the coordinator when something fires.

    `facts` is the structured data the LLM gets to reference. Anything that
    is not in `facts` does not exist as far as the System AI is concerned —
    the persona rule is "no invented details."

    `summary` is a single English line for the LLM and for log readability.
    """

    trigger_name: str
    severity: Severity
    facts: Dict[str, Any]
    summary: str
    # Per-instance dedup key. Two firings of the same trigger that share a
    # dedup_key within the cooldown window are treated as duplicates. Default:
    # just the trigger_name (so the trigger fires at most once per cooldown
    # for the whole user). Triggers can override for finer dedup, e.g.
    # `f"stale_pr:{oldest_branch}"`.
    dedup_key: Optional[str] = None
    suppressible: bool = False

    def effective_dedup_key(self) -> str:
        return self.dedup_key or self.trigger_name


class Trigger(ABC):
    """Base class for narrator triggers."""

    name: str  # set by @register_trigger
    cooldown_seconds: int = 24 * 60 * 60  # default daily

    @abstractmethod
    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        """Return a TriggerContext if the trigger should fire, else None.

        This method must be cheap. The coordinator calls it on every sweep
        and discards None results without state changes.
        """


# ── Registry ──────────────────────────────────────────────────────────────

registry: Dict[str, Trigger] = {}


def register_trigger(
    name: str,
    cooldown_seconds: int = 24 * 60 * 60,
) -> Callable[[Type[Trigger]], Type[Trigger]]:
    """Register a Trigger subclass under a stable name.

    Usage:
        @register_trigger("stale_pr", cooldown_seconds=86400)
        class StalePRTrigger(Trigger):
            async def check(self, db, user_id): ...
    """

    def decorator(cls: Type[Trigger]) -> Type[Trigger]:
        if name in registry:
            logger.warning(
                "narrator: trigger %r already registered (replacing)", name
            )
        cls.name = name
        cls.cooldown_seconds = cooldown_seconds
        registry[name] = cls()
        return cls

    return decorator


def list_triggers() -> List[str]:
    """Return the names of all registered triggers, sorted."""
    return sorted(registry.keys())
