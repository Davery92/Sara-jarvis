"""Persistent request-budget ledger.

Ceiling per the plan: 2,800 total model requests, 24h active testing. This
file is the single source of truth for "how many have we spent", checked
before every request across process invocations (each stage runs as a
separate `docker compose exec` call).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LEDGER_PATH = Path(__file__).resolve().parent / "artifacts" / "ledger.json"
REQUEST_CEILING = 2800


class BudgetExceeded(RuntimeError):
    pass


def _load() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {"total_requests": 0, "started_at": None, "by_stage": {}}


def _save(state: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(state, indent=2))


def record(stage: str, n: int = 1) -> int:
    """Record n requests spent under `stage`. Returns new total. Raises
    BudgetExceeded if this would cross the ceiling -- caller decides whether
    to stop or (for an already-in-flight conversation) finish the turn and
    then stop."""
    state = _load()
    if state["started_at"] is None:
        state["started_at"] = time.time()
    state["total_requests"] += n
    state["by_stage"][stage] = state["by_stage"].get(stage, 0) + n
    _save(state)
    if state["total_requests"] > REQUEST_CEILING:
        raise BudgetExceeded(
            f"total requests {state['total_requests']} exceeds ceiling {REQUEST_CEILING} "
            f"(stage={stage})"
        )
    return state["total_requests"]


def remaining() -> int:
    state = _load()
    return REQUEST_CEILING - state["total_requests"]


def report() -> dict:
    state = _load()
    elapsed_h = (time.time() - state["started_at"]) / 3600 if state["started_at"] else 0.0
    return {**state, "elapsed_hours": round(elapsed_h, 2), "remaining": REQUEST_CEILING - state["total_requests"]}
