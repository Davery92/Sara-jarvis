"""Redacted effective-settings and code-provenance snapshot — harness/
thinking/personality plan, Phase 0.

Why this exists: an earlier evaluation claimed "the running service reflects
the current working tree" from a bind mount and a container-start timestamp
alone. That was wrong — `jarvis-backend-1` runs `uvicorn` with no `--reload`,
so a file edited on disk after the process started is NOT what the running
process has in memory, and there was no way to check that except by hand
(`docker inspect` + `stat` + arithmetic). This endpoint automates exactly
that check, going forward, for the modules most likely to matter: it hashes
each one ONCE, at first import (i.e., at process startup, since Python
modules import once), and compares that frozen hash against a fresh read of
the file on disk on every request.

What this endpoint deliberately does NOT do: assert that a hash match PROVES
the in-memory code is byte-identical to disk (a module could theoretically
be patched in memory after import), and does not assert that a hash
mismatch tells you what specifically changed. It answers one narrow,
useful question — "has this file on disk changed since this process
started?" — honestly, and leaves the rest to a restart plus this same
endpoint checked again after.

No secrets, no prompt contents, no soul text: prompt "version" is reported
as a hash only.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.user import User

router = APIRouter()

_PROCESS_STARTED_AT = time.time()

# Files whose in-memory-vs-disk drift has actually mattered for this
# project (the chat orchestration entrypoint, the reasoning filter, the
# persona builder, the final-assembly boundary, and the markup-leak guard).
# Add to this list as new hot paths turn out to matter; it is intentionally
# not "every file in the repo" — that would make the per-request hashing
# cost real and the report noisy.
_WATCHED_FILES = {
    "main_simple": "app/main_simple.py",
    "chat_reasoning": "app/services/chat_reasoning.py",
    "chat_system_prompt": "app/prompts/chat_system_prompt.py",
    "chat_assembly": "app/services/chat_assembly.py",
    "text_utils": "app/core/text_utils.py",
    "dialogue_state": "app/services/dialogue_state.py",
    "tool_mutation": "app/services/tool_mutation.py",
    "mtp_control": "app/services/mtp_control.py",
}

# App root, resolved from this file's own location (app/routes/debug_runtime.py
# -> app/routes -> app -> repo root), so this works whether the process runs
# from /app in the container or a host checkout during tests.
_APP_ROOT = Path(__file__).resolve().parent.parent.parent


def _hash_file(path: str) -> Optional[str]:
    """Hash a file given either an absolute path or one relative to
    `_APP_ROOT`. Absolute-path support exists so the drift-detection logic
    itself is testable against a throwaway temp file, without writing into
    the real repo checkout."""
    p = Path(path)
    if not p.is_absolute():
        p = _APP_ROOT / p
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


# Captured once, at first import of this module — which happens at process
# startup, since `app.include_router(debug_runtime_router)` runs during
# `app.main_simple` module load. This is "what the process actually has."
_HASH_AT_STARTUP: Dict[str, Optional[str]] = {
    name: _hash_file(rel) for name, rel in _WATCHED_FILES.items()
}


def _code_provenance() -> list:
    rows = []
    for name, rel in _WATCHED_FILES.items():
        current = _hash_file(rel)
        started = _HASH_AT_STARTUP.get(name)
        rows.append({
            "module": name,
            "path": rel,
            "hash_at_process_startup": (started or "")[:16] or None,
            "hash_on_disk_now": (current or "")[:16] or None,
            # A precise, narrow claim — see module docstring for what this
            # does and does not prove.
            "disk_still_matches_what_this_process_loaded": (
                started is not None and started == current
            ),
        })
    return rows


@router.get("/debug/chat-runtime")
async def chat_runtime(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Effective chat settings and code provenance for the signed-in user's
    process — redacted, no secrets, no prompt contents."""
    from sqlalchemy import text as _sa_text
    from app.main_simple import (
        CHAT_ENABLE_THINKING, CHAT_REASONING_EFFORT, LOCAL_GENERATION_MODE,
        LOCAL_MTP_DEPTH, CHAT_PRESENCE_PENALTY, CHAT_TURN_DEADLINE_S,
        CHAT_MAX_OUTPUT_TOKENS, CHAT_FORCED_FINAL_MAX_TOKENS,
        CHAT_DEFAULT_MODEL, OPENAI_MODEL, OPENAI_BASE_URL,
    )
    from app.services import llm_broker
    from app.services.soul_loader import load_soul_for_prompt
    from app.prompts.chat_system_prompt import build_chat_system_prompt, MAX_PROMPT_CHARS

    try:
        db.execute(_sa_text("SET TRANSACTION READ ONLY"))  # PostgreSQL-only; harmless best-effort
    except Exception:
        db.rollback()  # reset session state before the query below (e.g. SQLite in tests)
    soul = load_soul_for_prompt(db)
    db.rollback()

    # A representative prompt hash — NOT the soul content itself. Tool
    # names are a fixed synthetic set here (not this request's actual
    # tools) so the hash is comparable across calls without depending on
    # which tools got routed for an unrelated conversation.
    _sample_prompt = build_chat_system_prompt(
        "Sara", soul, ["calendar_list", "notes_create", "memory_search"],
    )

    return {
        "process": {
            "started_at": _PROCESS_STARTED_AT,
            "started_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(_PROCESS_STARTED_AT)),
            "uptime_s": round(time.time() - _PROCESS_STARTED_AT, 1),
            "pid": os.getpid(),
        },
        "code_provenance": _code_provenance(),
        "model": {
            "chat_default_model_global": CHAT_DEFAULT_MODEL,
            "openai_model_global": OPENAI_MODEL,
            "openai_base_url_global": OPENAI_BASE_URL,
            # llm_broker.resolve("chat") is the intended source of truth per
            # its own module docstring but is NOT yet wired into the live
            # chat_stream call site — reported here so that gap stays
            # visible instead of silently assumed closed.
            "llm_broker_resolve_chat": llm_broker.resolve("chat"),
            "llm_broker_wired_into_chat_stream": False,
        },
        "thinking": {
            "enabled": CHAT_ENABLE_THINKING,
            "reasoning_effort_requested": CHAT_REASONING_EFFORT if CHAT_ENABLE_THINKING else None,
            "generation_mode": LOCAL_GENERATION_MODE,
            "mtp_depth_configured": LOCAL_MTP_DEPTH,
            "presence_penalty_off_thinking": CHAT_PRESENCE_PENALTY,
        },
        "budgets": {
            "chat_max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
            "chat_turn_deadline_s": CHAT_TURN_DEADLINE_S,
            "forced_final_max_tokens": CHAT_FORCED_FINAL_MAX_TOKENS,
            "forced_final_max_tokens_configurable": True,  # CHAT_FORCED_FINAL_MAX_TOKENS, Phase 3
        },
        "prompt": {
            "builder": "app.prompts.chat_system_prompt.build_chat_system_prompt",
            "max_prompt_chars": MAX_PROMPT_CHARS,
            "sample_prompt_chars": len(_sample_prompt),
            "sample_prompt_sha256": hashlib.sha256(_sample_prompt.encode()).hexdigest(),
            "note": "hash only — no prompt or soul content is returned by this endpoint",
        },
    }
