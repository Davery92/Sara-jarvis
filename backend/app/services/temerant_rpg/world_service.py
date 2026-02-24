"""World time and passive world-motion helpers for scene-based Temerant RPG."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Tuple

from app.models.temerant_rpg import TemerantRpgWorldState

SLOTS = ("morning", "afternoon", "evening")


class WorldService:
    @staticmethod
    def next_slot(local_date: date, slot: str) -> Tuple[date, str]:
        current = (slot or "morning").strip().lower()
        if current not in SLOTS:
            current = "morning"
        idx = SLOTS.index(current)
        if idx < 2:
            return local_date, SLOTS[idx + 1]
        return local_date + timedelta(days=1), SLOTS[0]

    @staticmethod
    def advance_slots(world: TemerantRpgWorldState, count: int) -> str:
        d = world.local_date
        s = world.day_slot
        for _ in range(max(1, int(count))):
            d, s = WorldService.next_slot(d, s)
        world.local_date = d
        world.day_slot = s
        summary = (
            f"Time passes into {s} on {d.isoformat()}. "
            "Lectures, errands, and rumors move on without waiting for you."
        )
        world.last_advance_summary = summary
        return summary
