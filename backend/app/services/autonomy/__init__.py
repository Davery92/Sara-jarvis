"""
Autonomy services for Sara's cognitive architecture (Phase 4).

These services give Sara continuous awareness and proactive behavior:
- Proactive checks (consider if action is needed)
- Anticipation (prepare for upcoming events)
- Memory consolidation (nightly processing)
- Idle processing (productive use of quiet time)
- Worker coordination (prevent conflicts)
"""

from .proactive import ProactiveService, get_proactive_service
from .anticipation import AnticipationService, get_anticipation_service
from .coordination import WorkerCoordinator, get_coordinator

__all__ = [
    "ProactiveService",
    "get_proactive_service",
    "AnticipationService",
    "get_anticipation_service",
    "WorkerCoordinator",
    "get_coordinator",
]
