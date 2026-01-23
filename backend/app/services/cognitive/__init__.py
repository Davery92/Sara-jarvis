"""
Cognitive architecture services for Sara.

This package provides the core services for Sara's cognitive capabilities:
- RawBuffer: Captures and stores all incoming sensory data
- WorkingMemory: Sara's conscious scratchpad and context
- ConsolidationAgent: Compresses inputs into digestible context
- UserStateInference: Infers user's current state and availability
"""

from app.services.cognitive.raw_buffer import RawBufferService
from app.services.cognitive.working_memory import WorkingMemoryService

__all__ = [
    "RawBufferService",
    "WorkingMemoryService",
]
