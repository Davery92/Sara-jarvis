"""Deployed-version truth (Phase 7).

Reads the git SHA + build time captured at deploy time so /health/version and
the interoception self-check can detect drift ("daemon is 3 commits behind").

Resolution order:
  1. backend/VERSION file (written by deploy/deploy.sh: "<sha> <iso8601>")
  2. GIT_SHA / GIT_BUILT_AT env vars
  3. "unknown" (dev volume-mount with no VERSION file)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


@lru_cache(maxsize=1)
def get_version() -> Dict[str, str]:
    sha = "unknown"
    built_at = None
    try:
        if _VERSION_FILE.exists():
            parts = _VERSION_FILE.read_text().strip().split()
            if parts:
                sha = parts[0]
            if len(parts) > 1:
                built_at = parts[1]
    except Exception:
        pass
    if sha == "unknown":
        sha = os.getenv("GIT_SHA", "unknown")
        built_at = built_at or os.getenv("GIT_BUILT_AT")
    return {"sha": sha, "short_sha": sha[:8] if sha != "unknown" else "unknown",
            "built_at": built_at or "unknown"}
