from datetime import date

from app.services.temerant_rpg.resolution_service import ResolutionService
from app.services.temerant_rpg.world_service import WorldService


class _FixedRng:
    def __init__(self, values):
        self._values = list(values)

    def randint(self, _a, _b):
        return self._values.pop(0)


def test_world_next_slot_wraps_to_next_day():
    d, slot = WorldService.next_slot(date(2026, 2, 20), "evening")
    assert d == date(2026, 2, 21)
    assert slot == "morning"


def test_world_next_slot_advances_within_day():
    d, slot = WorldService.next_slot(date(2026, 2, 20), "morning")
    assert d == date(2026, 2, 20)
    assert slot == "afternoon"


def test_resolution_outcome_partial(monkeypatch):
    monkeypatch.setattr(ResolutionService, "_rng", _FixedRng([2, 2]))
    result = ResolutionService.compute_total(
        attribute_value=3,
        skill_value=1,
        difficulty=8,
        circumstance_mod=0,
    )
    assert result["total"] == 8
    assert result["margin"] == 0
    assert result["outcome"] == "partial"


def test_resolution_outcome_disaster(monkeypatch):
    monkeypatch.setattr(ResolutionService, "_rng", _FixedRng([1, 1]))
    result = ResolutionService.compute_total(
        attribute_value=1,
        skill_value=0,
        difficulty=12,
        circumstance_mod=0,
    )
    assert result["margin"] <= -7
    assert result["outcome"] == "disaster"
