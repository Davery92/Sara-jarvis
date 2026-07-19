"""Capability manifest — Brain Alignment H6 (body schema).

Sara should know what limbs she has. Her prompt's tool list must reflect what
is actually callable at runtime, not hand-written prose that drifts out of sync
(the "I referenced places_save but it wasn't wired" bug, and its inverse).

Two guarantees:
  1. `verify_prompt_tool_references()` — a startup check that flags any tool the
     prompt prose claims (**tool_name**) that isn't actually callable, and logs
     a warning. Run once at import/startup.
  2. `not_wired_result()` — when the model calls a tool that isn't registered,
     the tool result says so plainly so Sara states it accurately instead of
     guessing about herself.
"""
from __future__ import annotations

import logging
import re
from typing import List, Set

logger = logging.getLogger(__name__)

# Tools handled by inline elif branches in the chat dispatch loop (not in the
# tool registry). Kept explicit so the consistency check knows they're real.
INLINE_CHAT_TOOLS: Set[str] = {
    "search_notes", "create_note", "list_notes", "list_folders", "delete_note",
    "create_reminder", "list_reminders", "complete_reminder",
    "start_timer", "list_timers", "stop_timer",
    "search_documents", "search_memory",
}


def callable_tool_names() -> Set[str]:
    """Every tool name that can actually be invoked from a chat turn:
    the registry's tools plus the inline chat tools."""
    names: Set[str] = set(INLINE_CHAT_TOOLS)
    try:
        from app.tools.registry import tool_registry
        names |= {t.name for t in tool_registry.get_all_tools()}
    except Exception as e:
        logger.debug(f"capability_manifest: registry read failed: {e}")
    return names


def verify_prompt_tool_references(prompt_text: str) -> List[str]:
    """Return the list of **bolded** tool-like tokens in the prose that are NOT
    callable. Logs a warning for each so drift is visible at startup."""
    # Tool tokens look like **snake_case_name** and contain an underscore or a
    # known verb prefix — avoids matching **The cardinal rule** etc.
    candidates = set(re.findall(r"\*\*([a-z][a-z0-9_]{2,})\*\*", prompt_text))
    tool_like = {c for c in candidates if "_" in c}
    callable_names = callable_tool_names()
    missing = sorted(t for t in tool_like if t not in callable_names)
    for name in missing:
        logger.warning(
            f"⚠️ capability drift: prompt prose references tool '{name}' which is "
            f"NOT callable (absent from registry and inline chat tools)."
        )
    return missing


def not_wired_result(tool_name: str) -> str:
    """In-voice tool-result text for a call to an unregistered tool."""
    return (
        f"The '{tool_name}' capability is not currently wired — you don't have that "
        "tool available right now. Tell David plainly that you can't do that yet, "
        "rather than pretending or guessing."
    )
