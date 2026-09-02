"""Daemon config — loaded from env (systemd EnvironmentFile or shell)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass


def _required(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"[acs-daemon] FATAL: env var {name} is required", file=sys.stderr)
        sys.exit(2)
    return val


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        print(f"[acs-daemon] FATAL: env var {name}='{raw}' is not an int", file=sys.stderr)
        sys.exit(2)
    if not (lo <= v <= hi):
        print(f"[acs-daemon] FATAL: env var {name}={v} outside [{lo}, {hi}]", file=sys.stderr)
        sys.exit(2)
    return v


@dataclass(frozen=True)
class Config:
    # Backend (where memory + heartbeats land)
    backend_url: str
    daemon_token: str

    # LLM (where she thinks)
    llm_url: str
    llm_model: str

    # Cadence
    tick_interval_seconds: int      # heartbeat cadence
    ticks_per_think: int            # 1 think per N ticks
    thinks_per_reflect: int         # 1 reflect per M thinks

    log_level: str


def _load() -> Config:
    return Config(
        backend_url=_required("ACS_BACKEND_URL"),
        daemon_token=_required("ACS_DAEMON_TOKEN"),
        llm_url=_optional("ACS_LLM_URL", "http://100.104.68.115:8081/v1"),
        llm_model=_optional("ACS_LLM_MODEL", "qwen3.8-27b"),
        tick_interval_seconds=_int("ACS_TICK_INTERVAL", 60, 5, 600),
        ticks_per_think=_int("ACS_TICKS_PER_THINK", 5, 1, 60),
        thinks_per_reflect=_int("ACS_THINKS_PER_REFLECT", 6, 1, 60),
        log_level=_optional("ACS_LOG_LEVEL", "INFO"),
    )


config = _load()
