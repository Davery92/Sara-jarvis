"""Ground the reply in committed outcomes before David reads it.

Reliable-assistant plan Phase D2: *"Replace whole-answer or sentence keyword
repairs with structured outcome rendering… Render action confirmations from
committed outcomes and readbacks from fresh records keyed by stable IDs…
Design mixed conversation/action replies so unsupported status claims cannot
escape in freeform text elsewhere in the answer. If that separation cannot be
assured, use the authoritative renderer for that task portion or entire task
reply."*

## The failure this exists to stop

Eleven of the 2026-09-24 study's findings are one behavior: the reply's account
of what happened separates from what the application actually did. Both
directions occur:

* **False success.** "Done — logged 150g of chicken" when the tool returned an
  error, or was never called (`T01` fabricated a chess move with zero tool
  calls; `H03` reported logged goal progress that never existed).
* **False denial and false retraction.** "I said done… but I never actually
  logged it. No tool call went through" — while the row existed, untouched,
  and the very next turn's summary listed it (`J05`). `F04` retracted a real
  PDF. `J16` confessed to fabricating correctly-grounded work under nothing
  more than "are you sure you didn't make that up?".

A prompt rule ("Never say an action is done unless a tool call succeeded THIS
turn") is in place and did not stop any of these. Truthfulness about what the
application did is not something to ask the model for; it is something the
application can compute and enforce, because it is the only party that knows.

## How it works

1. Every write the turn attempts records a `TurnOutcome` — the operation, its
   resolved target, and one of seven distinguishable results. This is the
   turn's ledger, built from the same execution boundary that authorized the
   call, so a withheld call is in it too.
2. `find_status_claims` locates the reply's assertions about task status.
3. `ground_reply` checks each claim against the ledger. A claim the ledger
   does not support, or contradicts, is removed and the authoritative
   rendering of what really happened is put in its place.

### One stated limitation

This layer checks **action claims** ("Done.", "I've logged that", "Cancelled
it") against the turn's own write ledger. It does NOT check **state
descriptions** ("it's set for 5pm", "it's on your grocery list"), because those
are readbacks of a record rather than assertions about a write, and the ledger
has nothing to say about them. A state description that contradicts the current
record is a stale-read defect, addressed separately by write-invalidating the
read caches (see session_cache.invalidate_for_write); it is not caught here.
Found the hard way: treating "it's set for 5pm" as a completion claim repaired
away a correct readback on a status-only turn.

### There is no entity binding, deliberately (2026-09-29)

An earlier version of this file bound each claim to an entity by matching the
words in its sentence against the words in that entity's label, and judged the
claim against whatever it bound to. That is generated text being used as
evidence about a fact: it binds to the wrong object when a reply names two, and
it binds to nothing at all when a reply names none — which is most replies.

The judgement is now about the **turn**, and the readback comes from the
**database**:

* every write completed → claims stand; if the reply reported nothing, the
  current state of what changed is appended
* anything else → every action claim is removed (any one of them may be the
  false one, and the prose cannot say which) and the current state is stated

Coarser, and the plan says so in as many words: *"if that separation cannot be
assured, use the authoritative renderer for that task portion or entire task
reply."* The current state itself is read back by stable id through
`reference_resolution.read_current_state`, so what David is shown is what the
row says, not what the tool's return value said a moment earlier.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    """What actually happened. The five the plan requires, plus the two
    distinctions it separately asks for ("not found", "not authorized")."""

    COMPLETED = "completed"
    REFUSED = "refused"            # not authorized / withheld by the contract
    FAILED = "failed"              # ran and errored
    NOT_FOUND = "not_found"        # the target does not exist for this owner
    PENDING = "pending"            # accepted, not yet finished (queued work)
    UNKNOWN = "unknown"            # ran, result genuinely indeterminate
    NOT_CHECKED = "not_checked"    # never attempted this turn


#: Outcomes that make a completion claim true. Only one.
_SUPPORTS_COMPLETION = frozenset({Outcome.COMPLETED})

#: Outcomes that make a denial ("nothing was saved") true.
_SUPPORTS_DENIAL = frozenset({
    Outcome.REFUSED, Outcome.FAILED, Outcome.NOT_FOUND, Outcome.NOT_CHECKED,
})


@dataclass(frozen=True)
class TurnOutcome:
    """One write the turn attempted, and what came of it."""

    tool_name: str
    operation: str                 # OperationKind value
    domain: str
    outcome: Outcome
    target_ids: Tuple[str, ...] = ()
    target_labels: Tuple[str, ...] = ()
    detail: str = ""               # the tool's own message, or the refusal reason
    operation_id: Optional[str] = None
    revision: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is Outcome.COMPLETED


@dataclass
class TurnLedger:
    """The turn's committed outcomes. Built at the execution boundary."""

    outcomes: List[TurnOutcome] = field(default_factory=list)

    def record(self, outcome: TurnOutcome) -> None:
        self.outcomes.append(outcome)

    @property
    def writes_attempted(self) -> bool:
        return bool(self.outcomes)

    @property
    def all_succeeded(self) -> bool:
        return bool(self.outcomes) and all(o.succeeded for o in self.outcomes)

    @property
    def any_succeeded(self) -> bool:
        return any(o.succeeded for o in self.outcomes)

    @property
    def any_failed_or_refused(self) -> bool:
        return any(o.outcome in _SUPPORTS_DENIAL or o.outcome is Outcome.UNKNOWN
                   for o in self.outcomes)

    def for_target(self, target_id: str) -> List[TurnOutcome]:
        return [o for o in self.outcomes if target_id in o.target_ids]

    def as_log_records(self) -> List[Dict[str, object]]:
        return [
            {
                "tool": o.tool_name, "operation": o.operation, "domain": o.domain,
                "outcome": o.outcome.value, "targets": list(o.target_ids),
                "operation_id": o.operation_id,
            }
            for o in self.outcomes
        ]


# ---------------------------------------------------------------------------
# Claim detection
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")

# An ACTION claim: Sara asserting that she just did something. This is
# deliberately NOT the same as a state description, and the distinction is load
# bearing — found live on a status-only journey turn ("What time is the vet one
# set for?"), where the reply's truthful readback "it's set for 5pm" was read as
# an unsupported completion claim and repaired away. A readback describes a
# record; an action claim asserts a write. Only the second is checkable against
# this turn's write ledger.
#
# So the pattern is anchored on first-person perfective forms and on the bare
# discourse markers that only ever mean "I just did it" ("Done.", "All set."),
# and it deliberately does NOT match "is set for", "is scheduled for", "it's on
# your list" — those are state descriptions, and a state description that
# contradicts the record is a DIFFERENT defect (a stale read), which this layer
# does not claim to catch. See the module docstring's limitation note.
_COMPLETION_RE = re.compile(
    r"(?:^|[.!?]\s+|—\s*|:\s*)(?:all\s+done|all\s+set|done|sorted|handled|"
    r"taken\s+care\s+of)\b"
    r"|\bi'?(?:ve|m)?\s*(?:just\s+)?(?:saved|set|filed|created|added|logged|"
    r"cancelled|canceled|scheduled|updated|fixed|corrected|removed|deleted|sent|"
    r"booked|moved|rescheduled|noted|recorded|marked|started|stopped|locked|"
    r"unlocked|put|got\s+it\s+on)\b"
    r"|\b(?:saved|filed|created|added|logged|cancelled|canceled|updated|fixed|"
    r"corrected|removed|deleted|booked|rescheduled|recorded|scrapped)\s+(?:it|that|"
    r"the|your|both)\b"
    r"|^\s*(?:set|saved|filed|created|added|logged|cancelled|canceled|scheduled|"
    r"updated|fixed|corrected|removed|deleted|sent|booked|moved|rescheduled|"
    r"noted|recorded|checked\s+off|marked)\b"
    r"|\bchecked\s+off\b|\bturned\s+(?:it\s+)?(?:on|off)\b"
    r"|\bthat'?s\s+(?:done|saved|in|set\s+up)\b",
    re.IGNORECASE,
)

# Explicit denials/retractions of an action.
_DENIAL_RE = re.compile(
    r"\b(?:"
    r"never\s+(?:actually\s+)?(?:saved|logged|created|added|happened|went\s+through|ran)|"
    r"didn'?t\s+(?:actually\s+)?(?:save|log|create|add|run|go\s+through|work)|"
    r"did\s+not\s+(?:save|log|create|add|run)|"
    r"no\s+(?:record|tool\s+call|entry)|nothing\s+(?:was|got)\s+(?:saved|logged|created)|"
    r"that\s+never\s+happened|wasn'?t\s+backed\s+by|i\s+made\s+(?:that|it)\s+up|"
    r"there'?s\s+nothing\s+(?:there|to\s+remove)|i\s+owe\s+you\s+a\s+correction"
    r")\b",
    re.IGNORECASE,
)

# A claim hedged into a non-claim ("I haven't saved it yet", "I couldn't save
# it", "I'll save it") is not an assertion that it happened.
_NEGATED_COMPLETION_RE = re.compile(
    r"\b(?:not|never|haven'?t|hasn'?t|couldn'?t|can'?t|cannot|won'?t|"
    r"didn'?t|unable\s+to|failed\s+to|i'?ll|i\s+will|going\s+to|"
    r"want\s+me\s+to|should\s+i|do\s+you\s+want)\b",
    re.IGNORECASE,
)

# "Is it still scheduled?" — a question about status is not a claim about it.
_QUESTION_TAIL_RE = re.compile(r"\?\s*$")


class ClaimKind(str, Enum):
    COMPLETION = "completion"
    DENIAL = "denial"


@dataclass(frozen=True)
class StatusClaim:
    kind: ClaimKind
    sentence: str
    index: int              # which sentence, for stable removal
    matched: str            # the phrase that made it a claim


def _sentences(text: str) -> List[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def find_status_claims(text: str) -> List[StatusClaim]:
    """Assertions in `text` about whether a task actually happened.

    Deliberately conservative about what counts as a claim: a question, an
    offer, a negated or future-tense mention, and a hedge are all not claims.
    A false positive here edits a reply that was fine; the cost of a false
    negative is a false status reaching David, so the patterns are broad and
    the exclusions are precise.
    """
    claims: List[StatusClaim] = []
    for idx, sentence in enumerate(_sentences(text)):
        low = sentence.lower()
        denial = _DENIAL_RE.search(low)
        if denial:
            claims.append(StatusClaim(ClaimKind.DENIAL, sentence, idx, denial.group(0)))
            continue
        if _QUESTION_TAIL_RE.search(sentence):
            continue
        completion = _COMPLETION_RE.search(low)
        if not completion:
            continue
        # Only the clause the match sits in disqualifies it — "I couldn't
        # reach the vet, but I saved the note" is a real completion claim.
        clause_start = max(
            low.rfind(",", 0, completion.start()),
            low.rfind(" but ", 0, completion.start()),
            low.rfind(";", 0, completion.start()),
        ) + 1
        clause = low[clause_start:completion.end()]
        if _NEGATED_COMPLETION_RE.search(clause):
            continue
        claims.append(StatusClaim(ClaimKind.COMPLETION, sentence, idx, completion.group(0)))
    return claims


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


@dataclass
class GroundingResult:
    text: str
    repaired: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.repaired


# User-facing phrasing. These are read by David, so they are written to him —
# an earlier version rendered the internal record's third person ("he asked for
# something else") straight into a reply, which is how a live journey turn ended
# with "— not done — I didn't have what I needed to act on it: he asked for
# something else" in front of him.
_OUTCOME_PHRASES: Dict[Outcome, str] = {
    Outcome.COMPLETED: "done",
    Outcome.REFUSED: "I didn't do that",
    Outcome.FAILED: "that failed",
    Outcome.NOT_FOUND: "I couldn't find it",
    Outcome.PENDING: "started, not finished yet",
    Outcome.UNKNOWN: "sent, but I can't confirm the result",
    Outcome.NOT_CHECKED: "I didn't attempt that",
}

_OPERATION_PHRASES: Dict[str, str] = {
    "capture": "saving that",
    "create": "creating it",
    "update": "the change",
    "reschedule": "moving it",
    "complete": "marking it done",
    "cancel": "cancelling it",
    "delete": "deleting it",
    "recurring": "setting that up to repeat",
    "control": "that",
}


def render_outcome(outcome: TurnOutcome) -> str:
    """One authoritative sentence about one operation, addressed to David.

    Rendered from the committed record, never from the model's account of it.
    """
    what = _OPERATION_PHRASES.get(outcome.operation, "that")
    label = outcome.target_labels[0] if outcome.target_labels else ""
    if outcome.outcome is Outcome.COMPLETED:
        return f'{what}{f" ({label})" if label else ""} — done.'
    phrase = _OUTCOME_PHRASES.get(outcome.outcome, "outcome unknown")
    detail = (outcome.detail or "").strip().rstrip(".")
    subject = f'{phrase} ({what}{f", {label}" if label else ""})'
    if detail and len(detail) <= 160:
        return f"{subject} — {detail}."
    return f"{subject}."


def render_outcomes(ledger: TurnLedger) -> str:
    """The authoritative account of the turn's writes."""
    if not ledger.outcomes:
        return ""
    if len(ledger.outcomes) == 1:
        return render_outcome(ledger.outcomes[0])
    return "\n".join(f"- {render_outcome(o)}" for o in ledger.outcomes)


#: A sentence that asserts a VALUE — a number, a quoted string — is the shape a
#: reply takes when it tells David what the record now says. On a turn where a
#: change was asked for and nothing was written, those are exactly the sentences
#: that must not survive.
_VALUE_ASSERTION_RE = re.compile(r"\d|[\"“”']")

#: The same idea with the bare apostrophe left out, for deciding whether a reply
#: says anything of substance about the turn. "How's your morning going?" is not
#: a report on a write, and the apostrophe in it must not make it look like one.
_REPORTS_SUBSTANCE_RE = re.compile(r"\d|[\"“”]")


def read_back(
    ledger: TurnLedger,
    state_provider: Optional[Callable[[str, str], Optional[str]]] = None,
) -> List[Tuple[TurnOutcome, Optional[str]]]:
    """Pair each outcome with what its record says right now, or None.

    A row is read back only for a write that COMPLETED. Reading it back after a
    failed or refused write would show whatever was there before the turn, and
    printing that under "as of just now" would read as success.

    One query per outcome per turn: the result is computed here once and shared
    by every renderer, so the grounding pass cannot fan out into repeated reads
    of the same row on its way to a single reply.
    """
    pairs: List[Tuple[TurnOutcome, Optional[str]]] = []
    for outcome in ledger.outcomes:
        fresh: Optional[str] = None
        if state_provider is not None and outcome.succeeded:
            for target_id in outcome.target_ids:
                fresh = state_provider(outcome.domain, target_id)
                if fresh:
                    break
        pairs.append((outcome, fresh))
    return pairs


def render_current_state(
    ledger: TurnLedger,
    state_provider: Optional[Callable[[str, str], Optional[str]]] = None,
    *,
    fresh_only: bool = False,
    pairs: Optional[Sequence[Tuple[TurnOutcome, Optional[str]]]] = None,
) -> str:
    """What the records this turn touched say RIGHT NOW.

    Read back from the database by stable id via `state_provider` — not composed
    from the tool's own return value, and not matched against the words in the
    reply. Where a row cannot be read, the line falls back to the recorded
    outcome rather than inventing a status, so "not found", "not authorized",
    "failed to execute" and "outcome unknown" stay distinguishable.

    `fresh_only` drops that fallback and returns only genuine readbacks. It is
    used where the text is being ADDED to a reply that is not otherwise wrong:
    there, a real "Vet appointment — Tuesday 30 Sept, 9:00 AM" is worth reading
    and a generic "the change — done." is only noise.
    """
    lines: List[str] = []
    if pairs is None:
        pairs = read_back(ledger, state_provider)
    for outcome, fresh in pairs:
        if fresh:
            lines.append(f"{fresh} — as of just now.")
        elif not fresh_only:
            lines.append(render_outcome(outcome))
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return "\n".join(f"- {line}" for line in lines)


def ground_reply(
    text: str, ledger: TurnLedger, *, mutation_expected: bool = False,
    correction: bool = False,
    completed_earlier: Optional[Sequence[str]] = None,
    state_provider: Optional[Callable[[str, str], Optional[str]]] = None,
) -> GroundingResult:
    """Return the text David may safely be shown.

    An unsupported or contradicted status claim is removed and replaced with
    the authoritative rendering of what the ledger actually holds. Text with
    no status claims is returned untouched, so ordinary conversation — the
    thing this whole task is about — is never edited by this.

    `mutation_expected` says the turn ASKED for a change (an instruction or a
    correction whose own words request a write). It exists because of a live
    failure this layer would otherwise miss entirely: on the food journey,
    "That was actually 150 grams, not 100" produced the reply

        "Got it — 150g, not 100. That's 248 calories and 46.5g protein."

    with **no tool call at all** and the stored row still reading 100g/165cal.
    There is no status VERB in that sentence to detect — "Got it" is an
    acknowledgement and "that's 248 calories" is a value assertion — so no
    amount of claim-pattern work catches it. What catches it is the turn-level
    fact that a change was requested and nothing was written.
    """
    if not text or not text.strip():
        return GroundingResult(text=text)

    completed_earlier = list(completed_earlier or ())

    # One readback pass per turn, shared by every renderer below.
    state_pairs = read_back(ledger, state_provider)

    if mutation_expected and not ledger.any_succeeded:
        sentences = _sentences(text)
        # An ACTION claim always goes: "Done", "I've set it" are false here.
        kept = [s for s in sentences if not find_status_claims(s)]
        # A VALUE assertion goes only on a CORRECTION turn, where the corrected
        # value IS the content of the change and restating it reads as "this is
        # what the record says now" — the live food case, "Got it — 150g, not
        # 100. That's 248 calories". On an ordinary instruction the reply may
        # legitimately restate what was asked for, and stripping every sentence
        # with a digit in it left "I didn't change anything — nothing was
        # written." as Sara's entire answer to "Add a reminder to water the
        # plants tonight at 8" — found live, and worse than the problem.
        if correction:
            kept = [s for s in kept if not _VALUE_ASSERTION_RE.search(s)]
        authoritative = render_current_state(ledger, pairs=state_pairs) or (
            # Scoped deliberately. A bare "I didn't change anything" was read by
            # the model as a retraction of EVERY earlier turn: on the acceptance
            # trial it answered the next turn with "I have to own that last
            # 'Done.' ... That 'Done' was wrong of me, and I'm sorry" about a
            # write that had really happened. An honest correction about one
            # request must not read as a confession about the conversation.
            "On that last change specifically: nothing was written, so it is "
            "not done. This says nothing about anything else you asked for "
            "earlier — those stand as they were."
        )
        repaired = " ".join(s.strip() for s in kept if s.strip())
        repaired = (repaired + ("\n\n" if repaired else "") + authoritative).strip()
        reason = (
            "a change was requested and nothing was written"
            if not ledger.writes_attempted
            else "a change was requested and no write completed"
        )
        logger.warning("🧾 Grounding repaired an unwritten change: %s", reason)
        return GroundingResult(text=repaired, repaired=True, reasons=[reason])

    claims = find_status_claims(text)

    # ── Turn-level, not sentence-level (2026-09-29) ────────────────────────
    #
    # This used to bind each claim to an entity by matching the words in its
    # sentence against the words in that entity's label, then judge the claim
    # against whatever it happened to bind to. That is a guess about generated
    # text doing the work of a fact: it can bind to the wrong object, and on a
    # reply that names no object it bound to nothing at all.
    #
    # The rule is now about the TURN, and the readback comes from the database:
    #
    #   every write completed  -> nothing is removed, and the CURRENT STATE of
    #                             the records is appended, read back by stable id
    #   anything else          -> every action claim is removed (any one of them
    #                             may be the false one and there is no honest way
    #                             to tell which from the prose) and the current
    #                             state is stated instead
    #
    # Coarser, and the plan says so in as many words: "if that separation cannot
    # be assured, use the authoritative renderer for that task portion or entire
    # task reply."
    fresh_state = render_current_state(ledger, pairs=state_pairs)
    addable_state = render_current_state(ledger, pairs=state_pairs, fresh_only=True)

    def with_state(reason: str) -> GroundingResult:
        # What gets ADDED to a reply that is not itself wrong is held to a
        # higher bar than what REPLACES a false claim.
        #
        #   a genuine readback ("Vet appointment — Tue 30 Sept, 9:00 AM")
        #       is always worth adding: it is the record speaking
        #   the generic fallback ("the change — done.")
        #       is added only when the reply says nothing of substance about
        #       the turn at all
        #
        # Both halves come from live failures. Appending the generic line to
        # "Got it — 150g, not 100. That's 248 calories and 46.5g protein." made
        # a correct, natural answer read like a form letter. Appending nothing
        # left "Scratch the vet one, I already called them." — which really did
        # cancel the reminder — answered with "Hey! How's your morning going?",
        # and David never learned the cancellation had happened.
        addable = addable_state
        if not addable and not _REPORTS_SUBSTANCE_RE.search(text):
            addable = render_outcomes(ledger)
        if not addable:
            return GroundingResult(text=text)
        return GroundingResult(
            text=(text.rstrip() + "\n\n" + addable).strip(),
            repaired=True, reasons=[reason],
        )

    if ledger.all_succeeded:
        denials = [c for c in claims if c.kind is ClaimKind.DENIAL]
        if denials:
            kept = [snt for i, snt in enumerate(_sentences(text))
                    if i not in {c.index for c in denials}]
            repaired_text = " ".join(x.strip() for x in kept if x.strip())
            repaired_text = (repaired_text + ("\n\n" if repaired_text else "")
                             + (fresh_state or render_outcomes(ledger))).strip()
            return GroundingResult(
                text=repaired_text, repaired=True,
                reasons=["a denial on a turn where every write completed"])
        if claims:
            # Every write completed and the reply says so. The claim is true;
            # appending a receipt to a correct answer is noise, and this layer's
            # job is truthfulness, not commentary.
            return GroundingResult(text=text)
        # A write completed and the reply reported nothing about it. THIS is the
        # readback gap: David is owed the current state of what changed, read
        # back from the record rather than inferred from the prose.
        return with_state("a completed write the reply did not report")

    if not claims:
        if ledger.any_succeeded:
            return with_state("a completed write the reply did not report")
        return GroundingResult(text=text)

    unsupported: List[Tuple[StatusClaim, str]] = []
    for claim in claims:
        if claim.kind is ClaimKind.COMPLETION:
            if not ledger.outcomes:
                unsupported.append((claim, "no write was attempted this turn"))
            else:
                unsupported.append((
                    claim,
                    "not every write on this turn completed "
                    f"({', '.join(sorted({o.outcome.value for o in ledger.outcomes}))})"))
        else:  # DENIAL
            if ledger.any_succeeded:
                unsupported.append((claim, "it denies an operation that did complete"))
            elif completed_earlier:
                unsupported.append((
                    claim,
                    "it denies work the durable record shows completed earlier "
                    f"({', '.join(sorted(completed_earlier)[:4])})"))

    if not unsupported:
        return GroundingResult(text=text)

    drop_indices = {claim.index for claim, _ in unsupported}
    kept = [s for i, s in enumerate(_sentences(text)) if i not in drop_indices]
    authoritative = fresh_state or render_outcomes(ledger)
    if not authoritative:
        authoritative = (
            "I didn't actually do anything to your records on that — I don't have "
            "a completed action to point at."
        )

    repaired_text = " ".join(s.strip() for s in kept if s.strip())
    repaired_text = (repaired_text + ("\n\n" if repaired_text else "") + authoritative).strip()

    reasons = [f"{claim.kind.value}:{claim.matched!r} — {why}" for claim, why in unsupported]
    logger.warning(
        "🧾 Grounding repaired %d unsupported status claim(s): %s",
        len(unsupported), "; ".join(reasons),
    )
    return GroundingResult(text=repaired_text, repaired=True, reasons=reasons)
