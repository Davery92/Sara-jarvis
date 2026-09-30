"""Thin adapters so run_turn's `context_router_override(message) -> (mode,
suppress_ambient)` signature can select real vs candidate classification.
"""
from __future__ import annotations

from app.services.context_router import classify_conversation_mode as _real_classify
from app.services.context_router import AMBIENT_SUPPRESS_MODES
from tests.conversation_eval.context_router_candidate import (
    classify_conversation_mode_candidate as _candidate_classify,
)


def real_router(message: str):
    mode = _real_classify(message)
    return mode, mode in AMBIENT_SUPPRESS_MODES


def candidate_router(message: str):
    mode = _candidate_classify(message)
    return mode, mode in AMBIENT_SUPPRESS_MODES
