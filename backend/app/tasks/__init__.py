"""
Celery tasks for Sara's cognitive architecture.

This package contains all background tasks organized by function:
- consolidation: Context compression and filtering
- working_memory: Memory management and refresh
- health: System health monitoring
- input_processing: Sensory input handling
- reflection: Meta-cognitive auditing (Phase 3)
- autonomy: Proactive behavior (Phase 4)
"""

from app.celery_app import celery_app

__all__ = ["celery_app"]
