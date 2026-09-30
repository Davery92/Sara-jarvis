"""One bounded, deterministic retry when an explicit request produced no call.

## The failure

David says "Scratch the vet one, I already called them." The turn identifies a
CANCEL, the reminder exists, the contract would authorize it — and the model
answers "Hey! How's your morning going?" without calling anything. Nothing is
wrong with the authorization, the tool, or the record. The one thing that had to
happen simply did not happen, and the turn ends.

The grounding layer catches the *reporting* half of this: David is told nothing
was written rather than being told it was. That is honest and it is not enough.
He asked for something explicit, it did not happen, and asking again is exactly
the "repeated intervention" this whole task exists to remove.

## What recovery is, and what it deliberately is not

It is **not** a second generation. Asking the model again costs budget, is not
reproducible, and fails in the same way when the same turn is retried — this
runs on the application's own deterministic parse of David's words, and either
produces exactly one call or produces nothing.

It is **not** a widening of authority. The recovered call goes back through
`execute_tool`, which means the operation contract decides it on exactly the
same evidence as a model-issued call would face. Recovery can only ever supply
a call the contract was already willing to allow; it cannot supply consent.

It is **bounded** in four separate ways, each of which alone would stop a
runaway:

1. **One attempt per turn.** The caller sets a flag before executing.
2. **One identified operation.** If `requested_operations` does not name
   exactly one non-read operation, there is nothing to recover — an unclear
   instruction is a CLARIFY, not a guess (see `unresolved_imperative`).
3. **One resolved target.** Zero candidates or two candidates both stop it.
   "The vet one" with two matching rows is an ask, never a coin flip.
4. **No invented arguments.** Only operations whose arguments are entirely
   derivable from David's own words are eligible. CREATE is not, and is not on
   the list: composing a title and a time from prose is the model's job, and
   getting it wrong writes a wrong row rather than writing nothing.

Idempotency is the execution boundary's, not this module's: the recovered call
carries the turn's own operation id, so the durable receipt refuses a second
execution of the same operation exactly as it would for a model-issued call.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveredCall:
    """A call the application derived from David's words, not from a model."""

    tool_name: str
    arguments: Dict[str, Any]
    reason: str


#: The operations recovery may supply, and the argument each needs beyond the
#: target id. An operation is eligible only when every argument it requires can
#: be read out of the user's own sentence.
#:
#: CREATE, CAPTURE and UPDATE are absent on purpose. Each needs content — a
#: title, an item, a new value — and deriving content from prose is precisely
#: the job this module refuses to do. A recovery that writes the wrong row is
#: worse than a turn that writes nothing and says so.
_RECOVERABLE = {
    "complete": ("daily_task_complete",),
    "cancel": ("reminders_cancel", "timers_cancel"),
    "reschedule": ("reminders_reschedule",),
}

#: Which argument each tool wants the resolved target id in.
_TARGET_ARG = {
    "reminders_cancel": "reminder_id",
    "reminders_reschedule": "reminder_id",
    "timers_cancel": "timer_id",
    "daily_task_complete": "task_id",
}

#: The argument a reschedule puts the new time in.
_TIME_ARG = {
    "reminders_reschedule": "new_time",
}

#: A time expression this module is willing to act on. Deliberately narrow: an
#: explicit clock time, or a date. "later", "soon", "sometime this week" are not
#: here, because a reschedule to a guessed instant is a wrong row.
_EXPLICIT_TIME_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}:\d{2}\s*(?:am|pm)?"
    r"|\d{1,2}\s*(?:am|pm)"
    r"|\d{4}-\d{2}-\d{2}(?:[ t]\d{2}:\d{2}(?::\d{2})?)?"
    r")\b",
    re.IGNORECASE,
)


def _offered(tools: Optional[Sequence[Any]]) -> frozenset:
    names = set()
    for entry in tools or ():
        if isinstance(entry, dict):
            fn = entry.get("function") or {}
            name = fn.get("name") or entry.get("name")
            if name:
                names.add(name)
        elif isinstance(entry, str):
            names.add(entry)
    return frozenset(names)


def recover(
    db: Session,
    owner_id: str,
    message: str,
    offered_tools: Optional[Sequence[Any]] = None,
) -> Optional[RecoveredCall]:
    """The one call this turn should have made, or None.

    None is the common and correct answer. Every condition below is a reason to
    return it, and none of them is a failure — a turn that cannot be recovered
    deterministically is a turn David is told the truth about instead.
    """
    from app.services.operation_contract import (
        OperationKind,
        OperationRequest,
        requested_operations,
    )
    from app.services.reference_resolution import DOMAIN_SPECS, resolve_for_request
    from app.tools.registry import tool_registry

    if not message or not message.strip() or not owner_id:
        return None

    requested = requested_operations(message) - {OperationKind.READ}
    if len(requested) != 1:
        # Zero: nothing was asked for. Two or more: the turn names more than one
        # operation and picking one is a guess.
        return None
    kind = next(iter(requested))
    candidates = _RECOVERABLE.get(kind.value)
    if not candidates:
        return None

    available = _offered(offered_tools)
    eligible = [
        name for name in candidates
        if name in tool_registry.tools
        and name in _TARGET_ARG
        and (not available or name in available)
    ]
    if not eligible:
        return None

    # Which domain David meant is settled by his own rows, not by which tools
    # happened to be on the menu. "Scratch the vet one" is offered both
    # `reminders_cancel` and `timers_cancel`; exactly one of those domains
    # contains a row whose words he used, and that is the answer. Two domains
    # each holding a match is a real ambiguity and stops recovery.
    hits = []
    for tool_name in eligible:
        target_arg = _TARGET_ARG[tool_name]
        domain = next(
            (name for name, spec in DOMAIN_SPECS.items() if target_arg in spec.id_args),
            None,
        )
        if domain is None:
            continue
        request = OperationRequest(
            request_id="recovery",
            conversation_id=None,
            owner_id=str(owner_id),
            tool_name=tool_name,
            arguments={},
            operation_kind=kind,
            domain=domain,
            # The arguments below are the application's, derived from David's
            # own sentence. Nothing here came from model output.
            argument_source="user",
        )
        try:
            resolution = resolve_for_request(db, request, message)
        except Exception as exc:  # a resolver failure is not a licence to act
            logger.warning(
                "request_recovery: resolution failed for %s: %s", tool_name, exc)
            continue
        if resolution.owner_mismatch or resolution.unresolvable:
            continue
        if len(resolution.candidates) != 1:
            # Zero: he did not name anything in this domain. Two: he named
            # something this domain holds twice, and that is a question.
            continue
        hits.append((tool_name, target_arg, resolution.candidates[0]))

    if len(hits) != 1:
        return None
    tool_name, target_arg, target = hits[0]

    arguments: Dict[str, Any] = {target_arg: target.target_id}

    time_arg = _TIME_ARG.get(tool_name)
    if time_arg:
        times = _EXPLICIT_TIME_RE.findall(message)
        if len(times) != 1:
            # No explicit time, or two of them. Either way the new instant is
            # not something this module knows, and it will not invent one.
            return None
        arguments[time_arg] = times[0].strip()

    return RecoveredCall(
        tool_name=tool_name,
        arguments=arguments,
        reason=(
            f"the turn asked for {kind.value} and no call was made; "
            f"exactly one of David's own rows matched his words"
        ),
    )
