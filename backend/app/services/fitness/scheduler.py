from typing import Dict, Any, Optional


class FitnessScheduler:
    """Handles push/skip requests and auto-reflow with constraints."""

    def propose_reflow(self, workout_id: str, reason: str, constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"proposed_slot": None, "status": "floating"}

