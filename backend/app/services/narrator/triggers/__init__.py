"""Narrator triggers — detectors that observe Sara's state and emit TriggerContexts.

A trigger has one job: query existing state and decide whether something
narrator-worthy just happened. It does not call the LLM, does not check
cooldowns, does not deliver. Those concerns live in coordinator/voice/dispatch.

Triggers self-register via the @register_trigger decorator at module import.
"""
from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
    registry,
)

# Importing for side effects (decorator registration).
from app.services.narrator.triggers import git  # noqa: F401
from app.services.narrator.triggers import errors  # noqa: F401
from app.services.narrator.triggers import fitness  # noqa: F401
from app.services.narrator.triggers import conversations  # noqa: F401
from app.services.narrator.triggers import food  # noqa: F401
from app.services.narrator.triggers import activity  # noqa: F401
from app.services.narrator.triggers import recovery  # noqa: F401

__all__ = ["Trigger", "TriggerContext", "register_trigger", "registry"]
