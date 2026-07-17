"""
Autonomy services for Sara's cognitive architecture (Phase 4).

These services give Sara continuous awareness and proactive behavior:
- Anticipation (prepare for upcoming events)
- Memory consolidation (nightly processing)
- Idle processing (productive use of quiet time)
- Worker coordination (prevent conflicts)
- Unified heartbeat + checkin_builder handle proactive behavior
"""

from .anticipation import AnticipationService, get_anticipation_service
from .coordination import WorkerCoordinator, get_coordinator

__all__ = [
    "AnticipationService",
    "get_anticipation_service",
    "WorkerCoordinator",
    "get_coordinator",
]
