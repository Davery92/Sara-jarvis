"""Resolve a reference once, owner-scoped, and reuse the result.

Reliable-assistant plan Phase C2: *"Resolve each reference once per operation,
owner-scoped, and reuse the result for authorization, execution, and
receipts."*

`target_authorization.py` (R01 round 4) established the right idea — look the
call's own argument up as a real database row, verify its owner, and check
whether the message actually referred to THAT row — and returns a bare bool.
A bool cannot express the three outcomes that matter differently:

* the reference matches exactly one of David's rows → act on it;
* it matches several → ask which, which is a useful answer;
* it matches none and he never mentioned this kind of thing → do not act.

So this module returns the structured `TargetResolution` the operation
contract consumes, and fixes two concrete defects found in the bool version:

1. **Short reference words were invisible.** `_distinctive_words` required
   four characters, so "the vet one" against a row titled "Vet appointment"
   shared nothing and the call was refused. The plan's own worked example
   ("Scratch the vet one") failed on a length constant. Minimum is 3 here,
   with a real stopword list doing the work instead of the length.
2. **No candidate search at all.** It only ever checked the row the call
   named. With a candidate search the "which one?" case becomes visible
   instead of collapsing into a refusal — and a call that names no id at all
   can still be authorized when the reference is unambiguous.

Domains without a resolver fall back to the documented domain-noun check, the
same conservative behavior as before, and say so via
`TargetResolution.unresolvable` rather than silently looking resolved.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.services.operation_contract import (
    OperationRequest,
    ResolvedTarget,
    TargetResolution,
    TARGET_BOUND_KINDS,
)

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")

# Words that carry no distinguishing power when matching a row's own label
# against what David said. Deliberately a stopword list rather than a length
# threshold: "vet", "gym", "dog", "car", "tax" are three letters and are
# exactly the words he uses to refer to things.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "have", "has", "had",
    "was", "were", "are", "you", "your", "about", "into", "onto", "over",
    "under", "new", "old", "one", "ones", "two", "all", "any", "not", "but",
    "its", "his", "her", "their", "our", "get", "got", "can", "will", "just",
    "now", "then", "them", "they", "she", "him", "out", "off", "put", "set",
    "day", "today", "tomorrow", "yesterday", "morning", "evening", "night",
    "week", "month", "year", "time", "min", "mins", "hour", "hours",
    # Domain nouns themselves: matching on these would only re-do the
    # domain-level check this is supposed to go beyond.
    "note", "notes", "task", "tasks", "item", "items", "reminder", "reminders",
    "timer", "timers", "research", "plan", "plans", "thread", "threads",
    "list", "lists", "event", "events", "meeting", "appointment", "appt",
    "calendar", "order", "orders", "food", "meal", "workout", "recipe",
})

_PLURAL_SUFFIXES = ("ies", "es", "s")


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def distinctive_words(text: Optional[str]) -> frozenset:
    """Content words of a label or a message, stemmed for plurals."""
    if not text:
        return frozenset()
    out = set()
    for w in _WORD_RE.findall(text.lower()):
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.add(_stem(w))
    return frozenset(out)


def label_referenced(message: str, label: Optional[str]) -> bool:
    """Do any of the row's own distinctive words appear in the message?"""
    label_words = distinctive_words(label)
    if not label_words:
        return False
    return bool(label_words & distinctive_words(message))


# ---------------------------------------------------------------------------
# Per-domain specs
# ---------------------------------------------------------------------------


class DomainSpec:
    """How to find one of David's rows in a domain, and what to call it.

    `open_filter` narrows the candidate search to rows a mutation could still
    sensibly land on (a pending reminder, an unchecked list item). It is NOT
    applied to the named lookup: a call naming an already-completed row must
    still resolve, so ownership is verified and the tool can report the real
    state rather than "not found".
    """

    def __init__(
        self,
        domain: str,
        model_path: str,
        id_args: Sequence[str],
        label_attrs: Sequence[str],
        owner_attr: str = "user_id",
        revision_attr: Optional[str] = "updated_at",
        open_filter: Optional[Callable[[Any], Any]] = None,
        id_prefix_ok: bool = False,
    ) -> None:
        self.domain = domain
        self.model_path = model_path
        self.id_args = tuple(id_args)
        self.label_attrs = tuple(label_attrs)
        self.owner_attr = owner_attr
        self.revision_attr = revision_attr
        self.open_filter = open_filter
        self.id_prefix_ok = id_prefix_ok

    def model(self):
        module_name, _, class_name = self.model_path.rpartition(".")
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name)

    def label_for(self, row: Any) -> str:
        return " ".join(
            str(getattr(row, a)) for a in self.label_attrs
            if getattr(row, a, None)
        )

    def revision_for(self, row: Any) -> Optional[str]:
        if not self.revision_attr:
            return None
        value = getattr(row, self.revision_attr, None)
        return value.isoformat() if hasattr(value, "isoformat") else (
            str(value) if value is not None else None
        )


def _pending_reminder(model):
    return model.is_completed.is_(False)


def _active_timer(model):
    return model.is_active.is_(True)


def _pending_task(model):
    return model.is_completed.is_(False)


def _upcoming_event(model):
    return model.is_completed.is_(False)


#: Keyed by `tool_mutation._tool_domain_stem(tool_name)` — the same stem the
#: contract puts in `OperationRequest.domain`, so the two never disagree.
DOMAIN_SPECS: Dict[str, DomainSpec] = {
    "reminders": DomainSpec(
        "reminders", "app.models.reminder.Reminder",
        id_args=("reminder_id", "id"),
        label_attrs=("title", "description"),
        open_filter=_pending_reminder,
    ),
    "timers": DomainSpec(
        "timers", "app.models.reminder.Timer",
        id_args=("timer_id", "id"),
        label_attrs=("title",),
        revision_attr="created_at",
        open_filter=_active_timer,
    ),
    "notes": DomainSpec(
        "notes", "app.models.note.Note",
        id_args=("note_id", "id"),
        label_attrs=("title",),
    ),
    "daily_task": DomainSpec(
        "daily_task", "app.models.daily_task.DailyTask",
        id_args=("task_id", "id"),
        label_attrs=("title", "description"),
        open_filter=_pending_task,
    ),
    "calendar": DomainSpec(
        "calendar", "app.models.calendar_event.CalendarEvent",
        id_args=("event_id", "id"),
        label_attrs=("title", "location"),
        open_filter=_upcoming_event,
    ),
    "research_plan": DomainSpec(
        "research_plan", "app.models.research_plan.ResearchPlan",
        id_args=("plan_id", "id"),
        label_attrs=("title", "objective"),
        id_prefix_ok=True,
    ),
}

#: Domains where only one instance can exist at a time, so a generic
#: reference ("that research task") is unambiguous by construction. Carried
#: over from `target_authorization._SINGLETON_DOMAINS` with the same reason.
SINGLETON_DOMAINS = frozenset({"research_plan"})


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

_MAX_CANDIDATES = 8


def _named_id(spec: DomainSpec, arguments: Dict[str, Any]) -> Optional[str]:
    for arg in spec.id_args:
        value = arguments.get(arg)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lookup_named(db: Session, spec: DomainSpec, owner_id: str, target_id: str):
    """(row, owner_mismatch). Deliberately queries WITHOUT the owner filter so
    another owner's row is distinguishable from a nonexistent one — the two
    are very different risks and the contract treats them differently."""
    model = spec.model()
    query = db.query(model)
    if spec.id_prefix_ok and len(target_id) < 36:
        query = query.filter(model.id.like(f"{target_id}%"))
    else:
        query = query.filter(model.id == target_id)
    row = query.first()
    if row is None:
        return None, False
    if str(getattr(row, spec.owner_attr, None)) != str(owner_id):
        return None, True
    return row, False


def _search_candidates(
    db: Session, spec: DomainSpec, owner_id: str, message: str,
) -> Tuple[ResolvedTarget, ...]:
    """David's own rows in this domain whose label shares a content word with
    what he said. Ranked by how many words match, capped."""
    message_words = distinctive_words(message)
    if not message_words:
        return ()
    model = spec.model()
    query = db.query(model).filter(getattr(model, spec.owner_attr) == owner_id)
    if spec.open_filter is not None:
        try:
            query = query.filter(spec.open_filter(model))
        except Exception:  # a column the disposable schema lacks
            pass
    # Bounded: the candidate search is an authorization aid, not a search
    # feature. 200 rows is far more than any realistic same-domain ambiguity
    # and keeps this off the critical path for a user with thousands of notes.
    rows = query.limit(200).all()
    scored: List[Tuple[int, ResolvedTarget]] = []
    for row in rows:
        label = spec.label_for(row)
        overlap = distinctive_words(label) & message_words
        if not overlap:
            continue
        scored.append((
            len(overlap),
            ResolvedTarget(domain=spec.domain, target_id=str(row.id),
                           label=label, revision=spec.revision_for(row)),
        ))
    if not scored:
        return ()
    scored.sort(key=lambda pair: (-pair[0], pair[1].target_id))
    best = scored[0][0]
    # Only rows matching AS WELL AS the best one are genuine candidates: with
    # "the vet one", a row titled "Vet appointment" (1 match) and a row titled
    # "Buy vet food and call the vet" (1 match) are both candidates and the
    # answer is to ask; a row matching on one incidental word when another
    # matches on three is not a real competitor.
    return tuple(t for score, t in scored[:_MAX_CANDIDATES] if score == best)


def resolve_for_request(
    db: Session, request: OperationRequest, message: str,
) -> TargetResolution:
    """Resolve the request's target once. Never raises: a resolver failure
    yields `unresolvable`, which the contract treats as "let the tool report
    the truth" rather than as authorization."""
    from app.services.tool_mutation import tool_domain_evidenced

    domain_ref = bool(tool_domain_evidenced(request.tool_name, message))
    spec = DOMAIN_SPECS.get(request.domain)
    if spec is None:
        return TargetResolution(unresolvable=True, domain_referenced=domain_ref)

    named_id = _named_id(spec, request.arguments)
    named: Optional[ResolvedTarget] = None
    owner_mismatch = False
    not_found = False

    if named_id:
        try:
            row, owner_mismatch = _lookup_named(db, spec, request.owner_id, named_id)
        except Exception as exc:
            logger.warning(
                "reference_resolution: named lookup failed for %s/%s: %s",
                request.tool_name, request.domain, exc,
            )
            return TargetResolution(unresolvable=True, domain_referenced=domain_ref)
        if owner_mismatch:
            return TargetResolution(owner_mismatch=True, domain_referenced=domain_ref)
        if row is None:
            not_found = True
        else:
            named = ResolvedTarget(
                domain=spec.domain, target_id=str(row.id),
                label=spec.label_for(row), revision=spec.revision_for(row),
            )

    try:
        candidates = _search_candidates(db, spec, request.owner_id, message)
    except Exception as exc:
        logger.warning(
            "reference_resolution: candidate search failed for %s: %s",
            request.domain, exc,
        )
        candidates = ()

    if spec.domain in SINGLETON_DOMAINS:
        # One instance can exist, so there is nothing to disambiguate and a
        # candidate search can only manufacture a false mismatch.
        candidates = (named,) if named is not None else ()

    return TargetResolution(
        named=named,
        candidates=candidates,
        owner_mismatch=False,
        not_found=not_found,
        unresolvable=False,
        domain_referenced=domain_ref,
        label_referenced=label_referenced(message, named.label if named else None),
    )


def resolve_if_needed(
    db_factory: Callable[[], Session], request: OperationRequest, message: str,
) -> Optional[TargetResolution]:
    """Resolve only for the operation kinds a resolution can change the
    decision for, so an ordinary create/capture never pays for a query.

    `db_factory` is called only when a resolution is actually needed, and the
    session is always closed here — the caller never has to.
    """
    if request.operation_kind not in TARGET_BOUND_KINDS:
        return None
    db: Optional[Session] = None
    try:
        db = db_factory()
        return resolve_for_request(db, request, message)
    except Exception as exc:
        logger.warning("reference_resolution: session unavailable: %s", exc)
        return TargetResolution(unresolvable=True)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Current state, read fresh, keyed by stable id
# ---------------------------------------------------------------------------
#
# Reliable-assistant plan D2: "render action confirmations from committed
# outcomes AND READBACKS FROM FRESH RECORDS KEYED BY STABLE IDS."
#
# The grounding layer used to decide what a reply was talking about by matching
# the words in its sentences against the words in an entity's label. That is a
# guess about generated text, and it is the wrong instrument twice over: it can
# bind a claim to the wrong object, and it can only ever say "supported" or
# "not supported" — never what is actually true right now. This reads the row
# back and says what it says.

def _reminder_state(row) -> str:
    from app.services.civil_time import as_utc, describe_instant
    when = describe_instant(as_utc(row.reminder_time)) if row.reminder_time else "no time"
    return f'"{row.title}" — {"cancelled" if row.is_completed else f"set for {when}"}'


def _timer_state(row) -> str:
    from app.services.civil_time import as_utc, describe_instant
    if row.is_completed:
        return f'"{row.title}" — finished'
    if not row.is_active:
        return f'"{row.title}" — cancelled'
    return f'"{row.title}" — running until {describe_instant(as_utc(row.end_time))}'


def _note_state(row) -> str:
    body = (row.content or "").split("## History")[0].strip()
    first = body.splitlines()[0] if body else ""
    return f'"{row.title}" — {first[:110]}' if first else f'"{row.title}"'


def _task_state(row) -> str:
    return f'"{row.title}" — {"done" if row.is_completed else "still open"}'


def _event_state(row) -> str:
    from app.services.civil_time import as_utc, describe_instant
    return f'"{row.title}" — {describe_instant(as_utc(row.start_time))}'


def _plan_state(row) -> str:
    return f'"{row.title}" — {getattr(row, "status", "unknown")}'


_STATE_RENDERERS = {
    "reminders": _reminder_state,
    "timers": _timer_state,
    "notes": _note_state,
    "daily_task": _task_state,
    "calendar": _event_state,
    "research_plan": _plan_state,
}


def read_current_state(
    db: Session, owner_id: str, domain: str, target_id: str,
) -> Optional[str]:
    """What the record says RIGHT NOW, or None if it cannot be read.

    Owner-scoped: another owner's row reads as None, never as content. None is
    also the honest answer for a domain with no renderer — the caller then says
    it cannot confirm rather than inventing a status.
    """
    spec = DOMAIN_SPECS.get(domain)
    renderer = _STATE_RENDERERS.get(domain)
    if spec is None or renderer is None or not target_id:
        return None
    try:
        row, owner_mismatch = _lookup_named(db, spec, owner_id, target_id)
        if owner_mismatch or row is None:
            return None
        return renderer(row)
    except Exception as exc:
        logger.warning("read_current_state failed for %s/%s: %s", domain, target_id, exc)
        return None
