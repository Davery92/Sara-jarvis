"""R01 review remediation round 4 (2026-09-27): proposal confirmation must
be bound to a STRUCTURED representation of the actual proposed operation,
target, and parameters — not merely "a long enough reply mentioning a
domain noun."

Round 3 required `presented_summary` (Sara's real, finalized reply text)
and checked it against `tool_domain_evidenced` at consume time — real
progress (a proposal can no longer be confirmed off a reply that never
substantively said anything), but review correctly identified it still
doesn't PROVE the user was shown the operation/target/parameters/recurring
scope that will actually execute: a reply mentioning the domain in passing
("your reminders are all up to date") would satisfy a bare domain check
without describing the specific action at all, and a flat DENIAL ("I can't
set that up without more detail") can be long and specific-sounding
without actually offering anything to confirm.

This module provides the stronger check:

- `render_structured_summary()` — a canonical, deterministic rendering of
  the tool call's own arguments (not the model's free-text description of
  them), used as the ground truth for what a genuine presentation must
  have referenced.
- `is_denial()` — a hard-denial detector: a refusal phrase with no
  accompanying invitation to confirm is not a proposal at all, and must
  never become confirmable.
- `presented_summary_matches_proposal()` — the combined check: not a
  denial, AND (the presented text references at least one distinctive
  word from the call's own arguments, OR — when there are no meaningful
  arguments to render — falls back to the domain-level check, same
  conservative default used throughout this module's siblings) AND, for
  tools that install STANDING/recurring authority, the presented text
  itself must actually frame this as recurring (not just the original
  request — the user must have been TOLD it would be standing).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.services.tool_mutation import has_recurring_scope, tool_domain_evidenced

_WORD_RE = re.compile(r"[a-z0-9]+")

# Argument keys unlikely to carry any human-recognizable identifying
# content (internal/structural fields) — skipped when rendering the
# structured summary so it doesn't get diluted with noise.
_SKIP_ARG_KEYS = {"user_id", "conversation_id", "session_id", "id"}

_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "have", "has",
    "true", "false", "none", "null",
}


def render_structured_summary(tool_name: str, arguments: Optional[Dict[str, Any]]) -> str:
    """Canonical, human-readable text built from the tool call's OWN
    arguments — the ground truth for "what was actually proposed,"
    independent of whatever the model's free-text reply happened to say.
    Includes `tool_name` for readability/logging; matching against this
    text is NOT how the authorization check works (see
    `_argument_words` below) — a reply mentioning only the tool's domain
    name, with none of its actual parameter values, must not pass merely
    because the domain word happens to overlap with the tool name itself.
    """
    if not arguments:
        return ""
    parts = []
    for key, value in arguments.items():
        if key in _SKIP_ARG_KEYS or value in (None, "", []):
            continue
        parts.append(f"{key}: {value}")
    return f"{tool_name} — " + "; ".join(parts) if parts else ""


def _distinctive_words(text: str) -> set:
    if not text:
        return set()
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 3} - _STOPWORDS


def _argument_words(arguments: Optional[Dict[str, Any]]) -> set:
    """Distinctive words from the ARGUMENT VALUES only — deliberately
    excludes the tool name itself, so a reply that mentions only the
    domain (e.g. "standing order") without any of the specific parameter
    values (the actual device, schedule, etc.) does not count as having
    shown the user what will actually execute."""
    if not arguments:
        return set()
    parts = []
    for key, value in arguments.items():
        if key in _SKIP_ARG_KEYS or value in (None, "", []):
            continue
        parts.append(str(value))
    return _distinctive_words(" ".join(parts))


# A denial phrase with no accompanying invitation to confirm is a flat
# "no" — there is nothing pending to confirm, and it must never become
# confirmable authority just because it happens to be long or specific.
_DENIAL_RE = re.compile(
    r"\bi\s+(?:can'?t|cannot|won'?t|will\s+not|do\s+not|don'?t)\b",
    re.IGNORECASE,
)
_OFFER_INVITE_RE = re.compile(
    r"\b(would you like|do you want|should i|shall i|let me know|say so|"
    r"confirm|go ahead|want me to|just say|tell me if)\b",
    re.IGNORECASE,
)


def is_denial(text: str) -> bool:
    """A hard denial: refuses the action with no invitation to confirm a
    proposed alternative. "I won't do that automatically — want me to do
    it just this once?" is NOT a denial (it invites confirmation, and IS
    a genuine pending proposal); "I can't do that without more detail."
    with nothing further IS a denial."""
    if not text:
        return False
    if not _DENIAL_RE.search(text):
        return False
    return not _OFFER_INVITE_RE.search(text)


def presented_summary_matches_proposal(
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    presented_summary: str,
    require_recurring: bool = False,
) -> bool:
    """The combined structural check. See module docstring."""
    if is_denial(presented_summary):
        return False

    arg_words = _argument_words(arguments)
    if arg_words:
        summary_words = set(_WORD_RE.findall((presented_summary or "").lower()))
        if not (arg_words & summary_words):
            return False
    else:
        # No meaningful arguments to render (e.g. a bare creation request
        # with everything still to be decided) — fall back to the
        # domain-level check, the same conservative default used
        # elsewhere in this repair when there's nothing more specific to
        # bind to.
        if not tool_domain_evidenced(tool_name, presented_summary):
            return False

    if require_recurring and not has_recurring_scope(presented_summary):
        # A tool that installs STANDING authority must have been
        # PRESENTED as standing/recurring — the user seeing "I can turn
        # the porch light on" without any recurring framing did not see
        # what will actually execute.
        return False

    return True
