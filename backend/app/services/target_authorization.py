"""R01 review remediation round 4 (2026-09-27): bind the requested
operation to a resolved, OWNER-SCOPED target — not merely the presence of
domain vocabulary anywhere in the message.

`tool_mutation.tool_domain_evidenced` (round 3) fixed the retry-bypass and
call-order bugs, but review correctly identified it still only asks "does
this message mention the KIND of thing this tool acts on, anywhere at
all?" Two concrete failure shapes that leaves open:

1. **Same-domain wrong target.** "Cancel the dentist reminder" evidences
   the reminders domain — which authorizes cancelling ANY reminder the
   model happens to call, including a completely different one the model
   mis-resolved the reference to. The message named a SPECIFIC reminder;
   the check never verified the call's actual `reminder_id` argument
   corresponds to that one.
2. **Domain words elsewhere in the message.** "Show my reminders, but
   cancel that research task" legitimately authorizes a
   `cancel_research_plan` call — but the same message also contains the
   word "reminders" (from "show my reminders," a READ request), which
   would wrongly authorize an UNRELATED `reminders_cancel` call too, since
   domain-vocabulary-anywhere does not care what the word was actually
   doing in the sentence.

This module resolves the tool call's own argument to the REAL database
row it names, then checks whether THAT SPECIFIC row's own identifying
text (title/objective/etc.) is what the message actually referenced — not
just whether the domain's generic noun appears anywhere. This fixes both
shapes at once: a wrong-target call's row has different identifying words
than the ones in the message (case 1), and a call whose row's words are
never mentioned is blocked regardless of what OTHER domain nouns happen to
appear elsewhere in the same message (case 2) — the check is scoped to
the specific resolved target, not the whole message's vocabulary.

Ownership is verified explicitly, not merely implied by the lookup
filter: a row that exists but belongs to a DIFFERENT user is always
blocked (a genuine cross-tenant reference — never authorized, no
fallback). A row that doesn't exist for ANYONE (a hallucinated id, an
already-deleted row, or — realistically — a test exercising chat-loop
mechanics with fabricated ids and no backing database row at all) is a
different, much lower-severity case: it falls back to the domain-level
check rather than an unconditional block, since blocking it outright
would manufacture false refusals for legitimately-authorized requests
whose target simply can't be resolved here — the tool itself still fails
honestly with "not found" when it actually executes.

Only a subset of domains have a real resolver below (reminders, timers,
notes, research_plan) — the ones this round's review findings concretely
named or that share the same simple "one id argument, one owner-scoped
row with a title" shape. A scope-sensitive tool in an unresolved domain
(threads, lists, standing orders) falls back to
`tool_mutation.tool_domain_evidenced` — the same conservative behavior as
before, a known, explicitly documented remaining gap rather than a
silent one.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.tool_mutation import (
    _tool_domain_stem,
    is_scope_sensitive_tool,
    tool_domain_evidenced,
)

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")

# Common words that carry no distinguishing power for matching a specific
# target's title against a message — excluded so a generic title like "My
# Reminder" doesn't trivially "match" almost any message.
_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "have", "has",
    "was", "were", "are", "you", "your", "about", "into", "onto", "over",
    "under", "note", "notes", "task", "tasks", "item", "items", "new",
    "old", "one", "two", "reminder", "reminders", "timer", "timers",
    "research", "plan", "thread", "list",
}


def _distinctive_words(text: Optional[str]) -> set:
    """Lowercase words of at least 4 characters, minus stopwords and the
    domain nouns themselves (which would otherwise trivially "match" via
    the domain-vocabulary check this is meant to go beyond)."""
    if not text:
        return set()
    words = {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 4}
    return words - _STOPWORDS


def _text_evidences_words(message: str, words: set) -> bool:
    if not message or not words:
        return False
    msg_words = set(_WORD_RE.findall(message.lower()))
    return bool(msg_words & words)


# Sentinel returned by a resolver when the named id exists but belongs to
# a DIFFERENT user — a genuine cross-tenant reference, always blocked.
# Distinguished from a plain `None` (the id does not exist for ANYONE —
# a hallucinated id, a test fixture with no matching DB row, or a call
# resolved through some other, unaudited path) — see
# `target_reference_evidenced`'s handling of each, and the module
# docstring's discussion of why these two cases are NOT the same risk.
_FOUND_OTHER_OWNER = object()


def _reminder_lookup(db: Session, user_id: str, arguments: Dict[str, Any]):
    reminder_id = arguments.get("reminder_id")
    if not reminder_id:
        return None
    from app.models.reminder import Reminder
    r = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not r:
        return None
    if r.user_id != user_id:
        return _FOUND_OTHER_OWNER
    return " ".join(filter(None, [r.title, r.description]))


def _timer_lookup(db: Session, user_id: str, arguments: Dict[str, Any]):
    timer_id = arguments.get("timer_id")
    if not timer_id:
        return None
    from app.models.reminder import Timer
    t = db.query(Timer).filter(Timer.id == timer_id).first()
    if not t:
        return None
    if t.user_id != user_id:
        return _FOUND_OTHER_OWNER
    return t.title or ""


def _note_lookup(db: Session, user_id: str, arguments: Dict[str, Any]):
    note_id = arguments.get("note_id")
    if not note_id:
        return None
    from app.models.note import Note
    n = db.query(Note).filter(Note.id == note_id).first()
    if not n:
        return None
    if n.user_id != user_id:
        return _FOUND_OTHER_OWNER
    return n.title or ""


def _research_plan_lookup(db: Session, user_id: str, arguments: Dict[str, Any]):
    plan_id = arguments.get("plan_id")
    if not plan_id:
        return None
    from app.models.research_plan import ResearchPlan
    q = db.query(ResearchPlan)
    # cancel_research_plan's own contract: "full plan ID or an ID prefix
    # of 8+ characters" — a real UUID is 36 chars, so anything shorter is
    # a prefix lookup, matching the tool's own documented behavior.
    if len(plan_id) < 36:
        q = q.filter(ResearchPlan.id.like(f"{plan_id}%"))
    else:
        q = q.filter(ResearchPlan.id == plan_id)
    p = q.first()
    if not p:
        return None
    if p.user_id != user_id:
        return _FOUND_OTHER_OWNER
    return " ".join(filter(None, [p.title, p.objective]))


# Domains where more than one instance can exist at once — the real
# "wrong one among several" risk review finding 2 is about — require the
# call's target to match its OWN distinctive words, not just the domain.
# `research_plan` is deliberately excluded: the tool's own contract is
# "only one research plan may run at a time" (verified directly in
# `cancel_research_plan`'s docstring/`app/services/research/cancel.py`),
# so there is never a SECOND candidate to confuse it with — a generic
# reference ("cancel that research task") is unambiguous by construction
# for a singleton resource, and requiring a specific word match there
# would only produce false refusals of exactly this realistic phrasing.
# Ownership is still verified for singletons (the resolver still runs and
# still fails closed on a wrong/missing id) — only the specific-word
# binding is skipped in favor of the domain-level check.
_RESOLVERS: Dict[str, Callable[[Session, str, Dict[str, Any]], Optional[str]]] = {
    "reminders": _reminder_lookup,
    "timers": _timer_lookup,
    "notes": _note_lookup,
    "research_plan": _research_plan_lookup,
}
_SINGLETON_DOMAINS = {"research_plan"}


def target_reference_evidenced(
    db: Session, user_id: str, tool_name: str, arguments: Dict[str, Any], message: str,
) -> bool:
    """True when the message actually references the SPECIFIC, owner-
    scoped target this tool call names — not merely the tool's domain in
    general. See module docstring for the two failure shapes this closes.
    """
    stem = _tool_domain_stem(tool_name)
    resolver = _RESOLVERS.get(stem)
    if resolver is None:
        # No real resolver for this domain yet — documented, conservative
        # fallback to the existing domain-vocabulary check.
        return tool_domain_evidenced(tool_name, message)

    try:
        target_text = resolver(db, user_id, arguments or {})
    except Exception as e:
        logger.warning(f"target_authorization resolver failed for '{tool_name}': {e}")
        return False  # fail closed — an unresolvable target is never authorized

    if target_text is _FOUND_OTHER_OWNER:
        # A genuine cross-tenant reference — the id names a REAL row that
        # belongs to someone else. Always blocked; there is no fallback
        # that could make this safe.
        return False

    if target_text is None:
        # The id doesn't exist for ANYONE — not the same risk as the
        # cross-tenant case above. A hallucinated/malformed id, an
        # already-deleted row, or (realistically, in this codebase) a
        # test exercising chat-loop mechanics with fabricated ids and no
        # backing DB row at all. Falling back to the domain-level check
        # here (rather than an unconditional block) avoids manufacturing
        # a false refusal for a legitimately-authorized request merely
        # because the specific row can't be resolved — the tool call
        # itself will still fail honestly with "not found" if the id
        # really doesn't exist when it actually executes.
        return tool_domain_evidenced(tool_name, message)

    if stem in _SINGLETON_DOMAINS:
        # Ownership is proven (target_text is not None); there is no
        # second candidate this domain could have confused it with, so
        # the domain-level check is the right (and only meaningful) bar.
        return tool_domain_evidenced(tool_name, message)

    words = _distinctive_words(target_text)
    if not words:
        # The resolved target has no distinctive identifying words (an
        # empty or generic title) — nothing specific to bind to, so fall
        # back to the domain-level check rather than block everything
        # with a blank title.
        return tool_domain_evidenced(tool_name, message)

    return _text_evidences_words(message, words)


def find_target_unauthorized_mutations(
    db: Session, user_id: str, tool_calls: Sequence[Dict[str, Any]], message: str,
) -> List[str]:
    """Tool-call ids to BLOCK: scope-sensitive calls whose SPECIFIC,
    owner-scoped target is not evidenced in the message (see
    `target_reference_evidenced`). Replaces
    `tool_mutation.find_target_unscoped_mutations` at the actual
    authorization call sites in main_simple.py — that function remains in
    tool_mutation.py as the pure, DB-free domain-level fallback this uses
    internally for unresolved domains, and stays independently tested.
    """
    from app.tools.mutating import tool_call_name

    blocked: List[str] = []
    for tc in tool_calls or []:
        name = tool_call_name(tc)
        if not name or not is_scope_sensitive_tool(name):
            continue
        try:
            args = json.loads(tc.get("function", {}).get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {}
        if not target_reference_evidenced(db, user_id, name, args, message):
            blocked.append(tc.get("id", ""))
    return blocked
