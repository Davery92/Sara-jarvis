"""Core action resolution for scene-based Temerant RPG."""

from __future__ import annotations

import random
from typing import Dict, Any


class ResolutionService:
    _rng = random.SystemRandom()

    @staticmethod
    def infer_difficulty(action: str) -> int:
        text = (action or "").lower()
        if any(k in text for k in ("easy", "simple", "quick")):
            return 6
        if any(k in text for k in ("careful", "precise", "convince", "perform")):
            return 10
        if any(k in text for k in ("dangerous", "complex", "master", "forbidden")):
            return 14
        return 10

    @staticmethod
    def compute_total(
        *,
        attribute_value: int,
        skill_value: int,
        difficulty: int,
        circumstance_mod: int = 0,
    ) -> Dict[str, Any]:
        roll = ResolutionService._rng.randint(1, 6) + ResolutionService._rng.randint(1, 6)
        total = int(attribute_value) + int(skill_value) + int(circumstance_mod) + int(roll)
        margin = total - int(difficulty)

        if margin >= 5:
            outcome = "triumph"
        elif margin >= 1:
            outcome = "success"
        elif margin >= -2:
            outcome = "partial"
        elif margin <= -7:
            outcome = "disaster"
        else:
            outcome = "failure"

        return {
            "roll": roll,
            "total": total,
            "difficulty": int(difficulty),
            "margin": margin,
            "outcome": outcome,
        }

    @staticmethod
    def consequence_from_outcome(outcome: str) -> Dict[str, Any] | None:
        if outcome == "partial":
            return {"type": "cost", "text": "You get what you wanted, but it costs time or favor."}
        if outcome == "failure":
            return {"type": "setback", "text": "The attempt fails and your standing shifts against you."}
        if outcome == "disaster":
            return {"type": "harm", "text": "A sharp consequence lands: lost coin, injury, or public embarrassment."}
        return None
