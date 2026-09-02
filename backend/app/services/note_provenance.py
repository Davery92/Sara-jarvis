"""Which notes Sara wrote herself.

Ground-truth invariant 2: *Sara's words are not evidence.* Notes written by
deliberation, agent dispatch, or a research run are Sara talking to herself. Left
untagged they enter the same pools as David's own notes — `memory_recall` ranked
three "Salem MA Historical Guide - Completed" notes she had just written as the
top four hits for a chat turn, and `pkg_extractor` promoted the contents of a
draft reply into the knowledge graph as fact.

Producers stamp `SARA_GENERATED_TAG`; readers call `is_sara_generated` to skip it.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

SARA_GENERATED_TAG = "sara_generated"


def is_sara_generated(tags: Optional[Iterable[Any]]) -> bool:
    """True when a note's tag list marks it as Sara's own output."""
    if not tags:
        return False
    return any(str(tag).strip().lower() == SARA_GENERATED_TAG for tag in tags)


def with_sara_tag(tags: Optional[Iterable[Any]] = None) -> list:
    """Existing tags plus the provenance tag, without duplicating it."""
    existing = [str(tag) for tag in (tags or [])]
    if not is_sara_generated(existing):
        existing.append(SARA_GENERATED_TAG)
    return existing
