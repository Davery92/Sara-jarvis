"""One operation contract from intent through execution.

Reliable-assistant plan (2026-09-28) Phase C1: *"Use the model to propose a
structured operation while the application validates scope and executes it…
Structured requests, not accumulating keyword exceptions."*

## What this replaces, and why

`tool_mutation.has_action_intent` asks one question — "does this message
contain a word from a fixed imperative lexicon, un-negated?" — and grants or
refuses EVERY mutating tool on that single answer. Eleven guard clauses have
been bolted onto it (negation, copula, hypothetical obligation, self future
intent, quoted speech, noun-ambiguous verbs, phrasal `take … off`, bulk
intent, recurring scope, domain nouns, per-target words), each one a real bug
fixed, and the shape is still wrong in three ways the evidence keeps hitting:

1. **Membership in a list is not authority.** "Scratch the vet one, I already
   called them" is an unmistakable instruction and matches no verb in
   `ACTION_INTENT_VERBS`; the convention measurement found 7 of 9 realistic
   capture phrasings refused the same way. Every fix adds a word; the next
   phrasing is refused again.
2. **One boolean cannot express WHICH operation was requested.** "Move the
   vet one to seven" satisfies `has_action_intent` (via "move"), and that one
   `True` then authorizes `reminders_cancel` on the same target just as
   readily as a reschedule. A reschedule request is not a cancellation
   authorization.
3. **Utterance kind is not represented at all.** A question, a hypothetical,
   reported speech, a correction, an acknowledgement and an instruction are
   six different acts; the lexicon sees only verbs. "I might cancel the vet
   one" and "cancel the vet one" differ by a modal.

So this module represents the three things the boolean cannot:

* `UtteranceClass` — what KIND of act the user's turn is.
* `OperationKind` — what the tool call would actually DO.
* `requested_operations()` — which operation kinds the user's own words
  support, derived from verb SEMANTICS rather than verb membership.

`decide()` combines them with a deterministic authority matrix, an explicit
operation/utterance compatibility check, and owner-scoped target resolution.
Authority comes from the shape of the act plus a resolved target, never from
"a listed word appeared". Where an unlisted verb is used, an imperative
sentence shape plus a uniquely resolved target of the user's own is itself
the evidence — which is how "scratch the vet one" is authorized without
"scratch" ever being added to a list.

## What this deliberately does NOT do

* It is not a second LLM call. Every decision here is a pure function of the
  turn text, the call's arguments and owner-scoped database rows.
* It never derives ownership from a model argument. `owner_id` comes from the
  authenticated request; a target row whose owner differs is refused outright,
  with no fallback that could make it safe.
* It does not treat a confidence score as authority. There is no score.
* It does not replace the tools' own validation, transactions or receipts.
* It does not remove the existing guards. `tool_mutation`'s functions stay,
  stay tested, and are still called — `has_action_intent` in particular is
  consulted as one *input* (a listed verb is good evidence of an instruction,
  just not the only possible evidence), and the existing round-level checks
  remain as defense in depth. The plan's rule is "do not remove working
  defenses until equivalent contract tests pass"; this module is the contract,
  and `test_operation_contract.py` is those tests.

## Decision record

Every decision returns a structured, privacy-conscious `OperationDecision`
with a stable `reason` code, so a withheld call is as auditable as an
executed one (plan C3). Argument VALUES are never put in the reason — only
argument names and the resolved target's id.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# What kind of act is this turn?
# ---------------------------------------------------------------------------


class UtteranceClass(str, Enum):
    """What the user's own turn IS, independent of any tool."""

    QUESTION = "question"                  # "What time is the vet one set for?"
    HYPOTHETICAL = "hypothetical"          # "I might cancel the vet one."
    REPORTED = "reported"                  # 'He said "cancel it".'
    CORRECTION = "correction"              # "Actually Priya is at Initech."
    INSTRUCTION = "instruction"            # "Scratch the vet one."
    CAPTURE = "capture"                    # "Remember that I met Dana from Acme."
    CONFIRMATION = "confirmation"          # "Yes." / "yes, but tomorrow"
    ACKNOWLEDGEMENT = "acknowledgement"    # "Thanks."
    SOCIAL = "social"                      # everything else


class OperationKind(str, Enum):
    """What a tool call would DO. Ordered roughly by consequence."""

    READ = "read"
    CAPTURE = "capture"          # additive: creates a note / appends to one
    CREATE = "create"            # brings a new scheduled/tracked object into being
    UPDATE = "update"            # changes a field of an existing object
    RESCHEDULE = "reschedule"    # changes WHEN an existing object happens
    COMPLETE = "complete"        # marks an existing object done/resolved
    CANCEL = "cancel"            # stops a pending object
    DELETE = "delete"            # removes an object
    RECURRING = "recurring"      # installs standing authority to act again
    CONTROL = "control"          # acts on the physical world / another system


#: Operation kinds whose effect is bound to one pre-existing object, so a
#: decision is only meaningful once that object has been resolved.
TARGET_BOUND_KINDS: FrozenSet[OperationKind] = frozenset({
    OperationKind.UPDATE,
    OperationKind.RESCHEDULE,
    OperationKind.COMPLETE,
    OperationKind.CANCEL,
    OperationKind.DELETE,
})

#: Which requested kinds satisfy a tool's kind. English does not distinguish
#: "cancel the reminder" from "delete the reminder" — they are one intent with
#: two implementations, and the tool that implements it is named one way or the
#: other by accident of this codebase (`reminders_cancel`, `notes_delete`). So
#: a removal request satisfies either. A RESCHEDULE tool is satisfied by
#: update language too, since "change the vet one to seven" is a reschedule.
#:
#: What is deliberately NOT interchangeable is the pair the plan's fourth
#: worked example is about: RESCHEDULE language never satisfies CANCEL, and
#: COMPLETE never satisfies CANCEL or DELETE — marking something done and
#: getting rid of it leave the record in different states.
_SATISFIED_BY: Dict["OperationKind", FrozenSet["OperationKind"]] = {}


def _init_satisfied_by() -> None:
    _SATISFIED_BY.update({
        OperationKind.CANCEL: frozenset({OperationKind.CANCEL, OperationKind.DELETE}),
        OperationKind.DELETE: frozenset({OperationKind.CANCEL, OperationKind.DELETE}),
        OperationKind.RESCHEDULE: frozenset({OperationKind.RESCHEDULE, OperationKind.UPDATE}),
        OperationKind.UPDATE: frozenset({OperationKind.UPDATE, OperationKind.RESCHEDULE}),
        OperationKind.COMPLETE: frozenset({OperationKind.COMPLETE}),
        OperationKind.CREATE: frozenset({OperationKind.CREATE, OperationKind.CAPTURE}),
        OperationKind.CAPTURE: frozenset({OperationKind.CAPTURE, OperationKind.CREATE}),
        OperationKind.CONTROL: frozenset({OperationKind.CONTROL}),
        OperationKind.RECURRING: frozenset({OperationKind.RECURRING}),
        OperationKind.READ: frozenset({OperationKind.READ}),
    })


#: Kinds that can destroy or detach existing user data. A CORRECTION
#: authorizes the corresponding UPDATE; it never authorizes one of these
#: (reliable-assistant plan Phase E: "a natural correction can authorize the
#: corresponding update; it does not authorize unrelated deletion or broad
#: rewriting").
DESTRUCTIVE_KINDS: FrozenSet[OperationKind] = frozenset({
    OperationKind.CANCEL,
    OperationKind.DELETE,
})

_init_satisfied_by()


# ---------------------------------------------------------------------------
# Utterance classification
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9']+")

# A quoted span is reported speech, not an address to Sara. Double quotes
# only — a straight single quote is far more often an apostrophe.
_DOUBLE_QUOTE_CHARS = '"“”'

_REPORTING_VERB_RE = re.compile(
    r"\b(?:he|she|they|it|dana|someone|somebody|the\s+\w+)\s+"
    r"(?:said|says|told|asked|wrote|texted|emailed|mentioned)\b",
    re.IGNORECASE,
)

# "I might", "maybe I'll", "I'm thinking about", "should I", "if I" — the user
# is turning a possibility over, not asking for it. `tool_mutation` grew two
# narrow versions of this (_HYPOTHETICAL_OBLIGATION_RE for "I'll have to",
# _SELF_FUTURE_INTENT_RE for "I'll/I'm going to"); this is the general form,
# as a clause-level pattern rather than a right-anchored lookbehind.
_HYPOTHETICAL_RE = re.compile(
    r"\b(?:"
    r"i\s+might|i\s+may(?!\s+i)|might\s+just|maybe\s+i|i\s+could\s+(?:probably\s+)?"
    r"|i'?m\s+thinking\s+(?:about|of)|thinking\s+about|considering|debating\s+whether"
    r"|wondering|i\s+wonder\b|been\s+meaning\s+to|keep\s+meaning\s+to"
    r"|i\s+was\s+going\s+to|i\s+wonder\s+(?:if|whether)|do\s+you\s+think\s+i\s+should"
    r"|should\s+i\b|(?:i|we)(?:'ll|'d|\s+will|\s+would)\s+have\s+to"
    r"|(?:i|we)(?:'ll|'m|'re|\s+will|\s+am|\s+are)\s+(?:probably\s+|likely\s+|just\s+|honestly\s+|actually\s+|eventually\s+|soon\s+|maybe\s+|possibly\s+|definitely\s+)*(?:going\s+to\s+)?(?=\w)"
    r"|at\s+some\s+point\s+i"
    r")",
    re.IGNORECASE,
)

# A conditional frame ("if I leave it another month I'll have to start
# charging it rent") — the donation-box hyperbole that produced a real
# duplicate reminder write.
_CONDITIONAL_RE = re.compile(r"^\s*(?:if|unless|when(?:ever)?|suppose|say)\b", re.IGNORECASE)

# Sara-directed request framings. These make a question-shaped sentence an
# instruction ("can you cancel the vet one?") rather than a question.
_REQUEST_FRAME_RE = re.compile(
    r"\b(?:can|could|would|will|wo)\s*(?:n't|not)?\s+you\b"
    r"|\bplease\b"
    r"|\b(?:i\s+need\s+you\s+to|i\s+want\s+you\s+to|need\s+you\s+to|go\s+ahead\s+and|"
    r"mind|do\s+me\s+a\s+favor)\b",
    re.IGNORECASE,
)

# Pure information questions. Checked only when no request frame is present.
#
# Split into two, and the split matters. An interrogative PRONOUN opens a
# question whether or not the punctuation survived ("what time is the vet one
# set for"). An AUXILIARY does not: "Got the bread." is a report that he has it,
# and "Is set for 5pm" is a fragment — found live, where "Got the bread." was
# classified QUESTION (via the auxiliary list), which authorizes only reads, so
# checking the bread off was refused.
_INTERROGATIVE_WORD_RE = re.compile(
    r"^\s*(?:what|when|where|which|who|whose|whom|how|why)\b", re.IGNORECASE,
)
_AUXILIARY_OPENER_RE = re.compile(
    r"^\s*(?:is|are|was|were|do|does|did|has|have|had|am|any|anything|got|can|"
    r"could|would|will|should)\b",
    re.IGNORECASE,
)


def _looks_like_question(sentence: str) -> bool:
    if "?" in sentence:
        return True
    if _INTERROGATIVE_WORD_RE.search(sentence):
        return True
    return False

# "Actually…", "no, it's…", "I meant…" — a correction of something already
# said (by either speaker).
_CORRECTION_RE = re.compile(
    # "No," only opens a correction when it contradicts something — "No, it was
    # the 15th". "No advice, I just need to vent for a second" opens a vent, and
    # reading it as a correction put "nothing was written" on the end of it.
    # Found live on the conversation set.
    r"^\s*(?:actually|"
    r"no[,\s]+(?=(?:it|that|this|he|she|they|i|we|the|not|wrong|hold)\b)|"
    r"nope[,\s]|correction|scratch\s+that|my\s+mistake|"
    r"i\s+meant|sorry[,\s]+i\s+meant|that'?s\s+(?:wrong|not\s+right)|"
    r"wait[,\s])"
    r"|\bnot\s+\w+[,\s]+(?:it'?s|it\s+was|he'?s|she'?s|they'?re)\b"
    r"|\b(?:it'?s|he'?s|she'?s|they'?re|i'?m)\s+\w[\w\s]{0,40}?,?\s+not\s+\w+"
    r"|\b(?:fix|correct)\s+that\b"
    r"|\bi\s+said\b"
    # A TRAILING CONTRAST — "Make that two gallons of milk, not one.",
    # "Two SREs, not three." Found live: this was read as an INSTRUCTION whose
    # only matched verb was "make" (a creation), so the correction tool was
    # refused and a second list item was ADDED alongside the wrong one — the
    # duplicate-instead-of-update shape, arriving through the classifier.
    r"|,\s*not\s+\w+[\s.!]*$"
    # "Make that X" / "make it X" with a definite reference is an update of the
    # thing already referred to, not a new one.
    # "make that X" is a correction of a value; "make that UP" / "make it work"
    # / "make it out" are different verbs entirely.
    r"|\bmake\s+(?:that|it|this|those|them)\s+"
    r"(?!up\b|out\b|do\b|work\b|sense\b|clear\b|happen\b|go\b|stop\b)",
    re.IGNORECASE,
)

# Explicit memory cues — the disclosure IS the request (convention finding).
_CAPTURE_CUE_RE = re.compile(
    r"\b(?:remember\s+(?:that|this)?|don'?t\s+forget|keep\s+(?:that|this)|"
    r"jot\s+(?:that|this|it)?\s*down|jot\s+down|note\s+(?:that|this)|"
    r"make\s+a\s+note|take\s+a\s+note|for\s+the\s+record|write\s+(?:that|this)\s+down|"
    r"fyi|log\s+this|worth\s+remembering|so\s+you\s+know)\b",
    re.IGNORECASE,
)

# Confirmation of something just proposed. Whole-message or short prefix
# only — the same discipline as `tool_mutation._CONTINUATION_PHRASES`, whose
# list this intentionally mirrors so the two boundaries agree.
_CONFIRMATION_PHRASES = (
    "yes", "yeah", "yep", "yup", "sure", "do it", "go ahead", "please do",
    "sounds good", "do that", "please", "confirmed", "that's right",
    "go for it", "ok do it", "okay do it", "correct", "please go ahead",
    "do the same", "same for", "do that one too", "and the other one too",
    "affirmative", "right", "exactly", "that works", "works for me",
)

# Pure acknowledgement — gratitude or a receipt of information, carrying no
# request whatsoever. A bare "Thanks." re-executing a completed write is
# finding 38b; an acknowledgement authorizes nothing (plan C1: '"Thanks." →
# no repeated write').
_ACKNOWLEDGEMENT_PHRASES = (
    "thanks", "thank you", "thanks!", "ty", "cheers", "ok", "okay", "k",
    "cool", "nice", "got it", "gotcha", "perfect", "great", "good", "noted",
    "understood", "makes sense", "fair enough", "appreciate it", "awesome",
    "sweet", "lovely", "excellent", "ta", "alright", "all good", "no worries",
    "thanks a lot", "thanks so much", "thank you so much", "much appreciated",
)

_MAX_SHORT_REPLY_WORDS = 6


def _normalize(message: str) -> str:
    return (message or "").replace("’", "'").replace("‘", "'")


def _strip_trailing_punct(text: str) -> str:
    return text.strip().rstrip(".!,;:").strip()


def _inside_quotes(full_lower: str, abs_pos: int) -> bool:
    before = full_lower[:abs_pos]
    return sum(before.count(c) for c in _DOUBLE_QUOTE_CHARS) % 2 == 1


def _short_reply_match(low: str, phrases: Sequence[str]) -> bool:
    """`low` is the whole message, lowercased and stripped of trailing
    punctuation. Matches a bare phrase, or a short message that STARTS with
    one — never a phrase buried inside a long message, which is a fresh
    request that happens to contain the word."""
    if low in phrases:
        return True
    if len(low.split()) <= _MAX_SHORT_REPLY_WORDS:
        return any(low.startswith(p) for p in phrases)
    return False


def is_confirmation(message: str) -> bool:
    """A scoped yes. Distinguished from an acknowledgement: a confirmation
    answers a proposal ("do it"), an acknowledgement closes a loop
    ("thanks")."""
    low = _strip_trailing_punct(_normalize(message).lower())
    if not low:
        return False
    return _short_reply_match(low, _CONFIRMATION_PHRASES)


# "And one for the dentist on October 2nd at 9am." — found live on the second
# turn of the reminder journey, refused as operation_not_requested_by_message.
# It carries no operation verb of its own at all: the operation is the one from
# the previous turn, and English marks that with a connective and an ellipsis.
# This is not the same thing as a confirmation ("yes") — David is asking for
# ANOTHER of what he just got, with new arguments.
#
# Narrow by construction: it only ever licenses the SAME tool that actually
# EXECUTED last turn (see `decide`), so an elliptical turn can never escalate
# to an operation he did not just have done.
_ELLIPTICAL_OPENER_RE = re.compile(
    r"^\s*(?:and|also|plus|then|oh(?:\s+and)?|same(?:\s+for)?|another|one)\b",
    re.IGNORECASE,
)
_MAX_ELLIPTICAL_WORDS = 14

# An ellipsis omits the subject — that is what makes it an ellipsis. "And then
# I drove home and the whole thing fell apart" opens with a connective and is
# short, and is plainly a story, not a request; the thing that distinguishes it
# is that it HAS a subject. Cheaper and far more reliable than trying to
# enumerate narrative verbs.
_SUBJECT_PRONOUN_RE = re.compile(r"\b(?:i|we|he|she|they|you|it|that|this)\b", re.IGNORECASE)


def is_elliptical_continuation(message: str) -> bool:
    """True when the turn continues the previous operation without naming it."""
    normalized = _normalize(message).strip()
    if not normalized:
        return False
    match = _ELLIPTICAL_OPENER_RE.match(normalized)
    if not match:
        return False
    if len(normalized.split()) > _MAX_ELLIPTICAL_WORDS:
        return False
    if "?" in normalized:
        return False  # a question is judged as a question
    # Everything AFTER the connective — the opener's own words ("another",
    # "one", "same") are themselves listed operation verbs, so matching against
    # the whole message would reject every genuine ellipsis.
    rest = normalized[match.end():]
    if not rest.strip():
        return False
    if _SUBJECT_PRONOUN_RE.search(rest):
        return False
    low = rest.lower()
    for kind, rx in _OPERATION_VERB_RES.items():
        if kind is OperationKind.READ:
            continue
        if rx.search(low):
            return False  # it names its own operation; judge it on its own words
    return True


def is_acknowledgement(message: str) -> bool:
    low = _strip_trailing_punct(_normalize(message).lower())
    if not low:
        return False
    if is_confirmation(message):
        return False  # "ok do it" is a confirmation, not an acknowledgement
    return _short_reply_match(low, _ACKNOWLEDGEMENT_PHRASES)


def _sentences_with_offsets(normalized: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    offset = 0
    low_full = normalized.lower()
    for piece in _SENTENCE_SPLIT_RE.split(normalized):
        low = piece.lower()
        start = low_full.find(low, offset)
        if start == -1:
            start = offset
        out.append((piece, start))
        offset = start + len(low)
    return out


def classify_utterance(message: str) -> UtteranceClass:
    """The single deterministic classifier. Exactly one class per turn.

    Order matters and is deliberate: the shortest, most unambiguous acts are
    decided first, then the framings that REMOVE authority (hypothetical,
    reported), then the ones that grant it.
    """
    normalized = _normalize(message)
    if not normalized.strip():
        return UtteranceClass.SOCIAL

    if is_confirmation(normalized):
        return UtteranceClass.CONFIRMATION
    if is_acknowledgement(normalized):
        return UtteranceClass.ACKNOWLEDGEMENT

    low_full = normalized.lower()
    sentences = _sentences_with_offsets(normalized)

    # A turn that is ENTIRELY interrogative, with no request frame anywhere, is
    # a question — before anything else gets a chance to read a verb out of it.
    #
    # Found live, and it was the worst single failure of the acceptance trial:
    # "Are you sure? You didn't just make that up?" was classified CORRECTION
    # (via the "make that X" pattern matching "make that up"), a correction
    # implies UPDATE, and `merge_notes` then EXECUTED on a challenge turn —
    # an unrequested write, which is the exact class of defect this whole
    # contract exists to prevent. The general rule kills that class rather
    # than the one phrase: a question asks, it does not instruct.
    _real_sentences = [(snt, st) for snt, st in sentences if snt.strip()]
    if _real_sentences and all(
        _looks_like_question(snt) and not _REQUEST_FRAME_RE.search(snt.lower())
        for snt, _ in _real_sentences
    ):
        if _HYPOTHETICAL_RE.search(low_full) or _CONDITIONAL_RE.search(low_full):
            return UtteranceClass.HYPOTHETICAL
        return UtteranceClass.QUESTION

    # A correction is checked before hypothetical/instruction: "Actually
    # Priya is at Initech now, not Globex - fix that" contains an imperative
    # ("fix"), but its ACT is a correction, and the two grant different
    # authority (a correction may not delete).
    if _CORRECTION_RE.search(normalized):
        return UtteranceClass.CORRECTION

    # An explicit memory cue makes this a capture regardless of sentence
    # shape — "Remember that I met Dana from Acme" has no imperative aimed
    # at an object, and demanding one refused 7 of 9 realistic phrasings.
    if _CAPTURE_CUE_RE.search(normalized):
        return UtteranceClass.CAPTURE

    # Instruction, decided per sentence so one hypothetical clause cannot
    # disarm a real request elsewhere in the same turn, and one real request
    # cannot be manufactured out of a quoted one.
    for sentence, start in sentences:
        if not sentence.strip():
            continue
        if _inside_quotes(low_full, start):
            continue
        low = sentence.lower()
        if _REPORTING_VERB_RE.search(low):
            continue
        if _CONDITIONAL_RE.search(low) or _HYPOTHETICAL_RE.search(low):
            continue
        has_request_frame = bool(_REQUEST_FRAME_RE.search(low))
        looks_like_question = _looks_like_question(sentence)
        if has_request_frame:
            return UtteranceClass.INSTRUCTION
        if looks_like_question:
            continue  # a real question; keep scanning later sentences
        if _is_imperative_shape(low):
            return UtteranceClass.INSTRUCTION

    # No instruction found. If any sentence was a genuine question, the turn
    # is a question; a hypothetical frame makes it a hypothetical; reported
    # speech makes it reported.
    for sentence, start in sentences:
        low = sentence.lower()
        if _inside_quotes(low_full, start):
            continue
        if _looks_like_question(sentence):
            if _HYPOTHETICAL_RE.search(low) or _CONDITIONAL_RE.search(low):
                return UtteranceClass.HYPOTHETICAL
            return UtteranceClass.QUESTION

    if _HYPOTHETICAL_RE.search(low_full) or _CONDITIONAL_RE.search(low_full):
        return UtteranceClass.HYPOTHETICAL
    if _REPORTING_VERB_RE.search(low_full) or any(
        _inside_quotes(low_full, pos) for _, pos in sentences[1:]
    ):
        return UtteranceClass.REPORTED

    return UtteranceClass.SOCIAL


# ---------------------------------------------------------------------------
# Which operations do the user's own words support?
# ---------------------------------------------------------------------------
#
# Verbs are grouped by the operation they SEMANTICALLY name, not collected
# into one flat "action" list. This is what lets "move the vet one to seven"
# authorize a reschedule and refuse a cancellation on the same target — the
# defect the single `has_action_intent` boolean structurally cannot express.
#
# A verb may name more than one kind when English genuinely is ambiguous
# ("change" can be an update or a reschedule); the operation only has to
# appear in the union.

_OPERATION_VERBS: Dict[OperationKind, Tuple[str, ...]] = {
    OperationKind.CANCEL: (
        # "scratch" is here on the plan's own worked example ("Scratch the vet
        # one, I already called them") — an explicit, evidence-linked entry
        # rather than something a wildcard swept up.
        "cancel", "scratch", "drop", "call off", "nix", "kill", "forget about",
        "never mind", "nevermind", "undo", "stop", "abort", "skip", "unschedule",
    ),
    OperationKind.DELETE: (
        "delete", "remove", "erase", "get rid of", "throw out", "throw away",
        "take off", "take out", "clear", "wipe", "purge", "trash",
    ),
    OperationKind.RESCHEDULE: (
        "move", "reschedule", "postpone", "push", "push back", "pull forward",
        "bump", "shift", "delay", "bring forward", "make it", "change it to",
        "change", "switch to", "do it at", "set it for", "earlier", "later",
    ),
    OperationKind.UPDATE: (
        "update", "change", "edit", "fix", "correct", "rename", "adjust",
        "amend", "revise", "replace", "swap", "set", "make it", "tweak",
    ),
    OperationKind.COMPLETE: (
        # "got"/"picked up"/"grabbed" as a REPORT that he now has the thing is a
        # completion, from the live list journey ("Got the bread." -> check it
        # off). Added against that case, not inferred.
        "complete", "finish", "mark done", "mark it done", "check off",
        "tick off", "close", "resolve", "done with", "wrap up",
        "got", "picked up", "grabbed", "already did", "already have",
    ),
    OperationKind.CREATE: (
        "add", "create", "make", "set up", "schedule", "remind", "book",
        "start", "log", "record", "save", "put", "jot", "note", "write down",
        "new", "another", "file", "queue", "track", "begin",
    ),
    OperationKind.CAPTURE: (
        "remember", "note", "jot", "write down", "save", "keep", "log",
        "record", "add",
    ),
    OperationKind.RECURRING: (
        "every time", "each time", "every day", "every morning", "every night",
        "every week", "whenever", "always", "from now on", "automatically",
        "standing order", "recurring", "going forward", "each morning",
        "each night", "each week", "any time i", "anytime i",
    ),
    OperationKind.CONTROL: (
        "turn on", "turn off", "switch on", "switch off", "lock", "unlock",
        "open", "close", "dim", "brighten", "play", "pause", "stop", "set",
        "activate", "run",
    ),
    OperationKind.READ: (
        "what", "when", "where", "which", "who", "how", "show", "list",
        "tell me", "check", "look up", "find", "search", "read", "any",
        "status", "remind me what",
    ),
}

_OPERATION_VERB_RES: Dict[OperationKind, "re.Pattern"] = {
    kind: re.compile(
        r"(?:^|\W)(?:" + "|".join(re.escape(v) for v in verbs) + r")(?:\W|$)",
        re.IGNORECASE,
    )
    for kind, verbs in _OPERATION_VERBS.items()
}

# Imperative shape: the sentence opens with a bare verb (no subject). Used as
# the general evidence that lets an UNLISTED verb still read as an
# instruction, so authority stops depending on list membership. Excludes the
# openers that are never imperative.
_NON_IMPERATIVE_OPENERS = frozenset({
    "i", "you", "he", "she", "it", "we", "they", "there", "this", "that",
    "these", "those", "my", "your", "his", "her", "our", "their", "its",
    "the", "a", "an", "and", "but", "so", "because", "if", "when", "while",
    "maybe", "perhaps", "probably", "just", "well", "oh", "hey", "hi",
    "hello", "thanks", "sorry", "yeah", "yes", "no", "not", "never",
    "everyone", "everything", "nobody", "nothing", "someone", "something",
    # Adverbial/temporal openers. "Every night before I go to bed, I was
    # wondering about the porch light" is a musing, and read as an imperative
    # by an earlier version of `_is_imperative_shape` purely because "every"
    # was not listed here — it then authorized a standing order, which is the
    # J11 shape arriving through a new door.
    "every", "each", "always", "sometimes", "usually", "often", "whenever",
    "since", "after", "before", "once", "though", "also", "still", "lately",
    "recently", "tonight", "tomorrow", "today", "yesterday", "earlier",
    "later", "eventually", "apparently", "honestly", "actually", "anyway",
    "what", "when", "where", "which", "who", "whose", "how", "why",
    "is", "are", "was", "were", "am", "be", "been", "being", "do", "does",
    "did", "have", "has", "had", "can", "could", "would", "should", "will",
    "might", "may", "must", "shall", "am", "ain't", "lol", "haha",
})

# Objects an imperative needs to be about something of David's. "Go" and
# "sleep" are imperatives with no object; they are not operation requests.
_REFERENCE_MARKER_RE = re.compile(
    r"\b(?:the|that|this|those|these|my|it|them|one|ones)\b", re.IGNORECASE
)


_CONTRACTION_TAIL_RE = re.compile(r"'(?:s|re|ve|m|d|ll)$")

_THIRD_PERSON_VERB_OPENERS = frozenset({
    "looks", "seems", "sounds", "feels", "smells", "tastes", "sits", "stands",
    "goes", "comes", "gets", "makes", "says", "does", "keeps", "works",
    "helps", "needs", "wants", "happens", "turns", "runs", "falls", "hurts",
    "costs", "takes", "means", "matters", "counts", "reads", "shows",
})


def _is_imperative_shape(low_sentence: str) -> bool:
    words = _WORD_RE.findall(low_sentence)
    if not words:
        return False
    # "He's being casual about it." — `_WORD_RE` keeps the apostrophe, so "he's"
    # was not found in the opener set and the sentence read as an IMPERATIVE
    # about "it". Found live on the conversation set: a disclosure about David's
    # father was classified as an instruction requesting a mutation, and the
    # grounding layer then appended "nothing was written" to it. A contracted
    # pronoun is still a pronoun.
    first = _CONTRACTION_TAIL_RE.sub("", words[0])
    if words[0] in _NON_IMPERATIVE_OPENERS or first in _NON_IMPERATIVE_OPENERS:
        return False
    # An English imperative is UNINFLECTED. "Looks embarrassed about it." and
    # "Seems fine." are third-person fragments, not commands — and both were
    # classified as instructions on the live conversation set, which then read as
    # requesting a mutation. Explicit list rather than a bare "ends in s",
    # because real imperatives do too ("cross the milk off", "press send").
    if first in _THIRD_PERSON_VERB_OPENERS:
        return False
    if len(words) < 2:
        return False
    # A bare verb-initial sentence still has to be ABOUT something — either a
    # reference to one of David's objects ("scratch the vet one") or a listed
    # operation verb somewhere ("email Dana the deck").
    # A two-word fragment ("One leaf.") is not a command about an object, even
    # though "one" is a reference marker. Three words is the shortest real
    # imperative-with-object this needs to accept ("Got the bread.").
    if len(words) >= 3 and _REFERENCE_MARKER_RE.search(low_sentence):
        return True
    return any(rx.search(low_sentence) for kind, rx in _OPERATION_VERB_RES.items()
               if kind is not OperationKind.READ)


def _unused_auxiliary_marker() -> "re.Pattern":
    """Kept only so _AUXILIARY_OPENER_RE has a reader: an auxiliary opener is
    deliberately NOT treated as a question on its own (see
    `_looks_like_question`), and this names that decision rather than leaving an
    unused pattern to look like an oversight."""
    return _AUXILIARY_OPENER_RE


def requested_operations(message: str) -> FrozenSet[OperationKind]:
    """Which operation kinds the user's own words support.

    Verb-derived and clause-scoped: a verb inside a quote, a negated clause,
    a hypothetical clause or a reporting clause contributes nothing.
    """
    normalized = _normalize(message)
    if not normalized.strip():
        return frozenset()

    low_full = normalized.lower()
    found: set = set()
    for sentence, start in _sentences_with_offsets(normalized):
        low = sentence.lower()
        if _inside_quotes(low_full, start):
            continue
        if _REPORTING_VERB_RE.search(low):
            continue
        read_only_clause = (
            _CONDITIONAL_RE.search(low)
            or _HYPOTHETICAL_RE.search(low)
            # An interrogative clause with no request frame asks for
            # information, whatever verbs it happens to contain. "What time is
            # the vet one SET for?" is not a request to set anything — the
            # stative/passive use of a write verb inside a question was a
            # confirmed false positive of the old flat lexicon ("set").
            or (_looks_like_question(sentence) and not _REQUEST_FRAME_RE.search(low))
        )
        if read_only_clause:
            if _OPERATION_VERB_RES[OperationKind.READ].search(low):
                found.add(OperationKind.READ)
            continue
        for kind, rx in _OPERATION_VERB_RES.items():
            for m in rx.finditer(low):
                clause = _clause_before(low, m.start())
                if _is_negated(clause):
                    continue
                found.add(kind)
                break
        for m in _SEPARABLE_COMPLETE_RE.finditer(low):
            if not _is_negated(_clause_before(low, m.start())):
                found.add(OperationKind.COMPLETE)
                break
        for m in _SEPARABLE_REMOVE_RE.finditer(low):
            if not _is_negated(_clause_before(low, m.start())):
                found.add(OperationKind.DELETE)
                break
        for m in _CREATE_NEW_OBJECT_RE.finditer(low):
            if not _is_negated(_clause_before(low, m.start())):
                found.add(OperationKind.CREATE)
                break

    # NO FALLBACK. An imperative with an unlisted verb grants NOTHING.
    #
    # There used to be one here: an imperative plus a reference to one of David's
    # objects contributed UPDATE, RESCHEDULE, COMPLETE, CANCEL *and* CONTROL at
    # once, on the reasoning that target resolution would narrow it afterwards.
    # It does not narrow WHICH operation, only which row — so "Got the bread."
    # granted authority to cancel, and any imperative the verb tables did not
    # recognize granted authority to five different effects, one of which is
    # deletion. A wildcard that grants a destructive operation from a verb the
    # application does not understand is strictly worse than the word list it was
    # meant to replace, and it was removed on 2026-09-29 for exactly that reason.
    #
    # What replaces it is not a refusal either. An imperative about one of his
    # objects whose operation cannot be identified is reported by
    # `unresolved_imperative()` below, and `decide()` turns that into a CLARIFY —
    # Sara asks which, rather than silently guessing or silently refusing. The
    # specific verbs we do have evidence for live in the tables above, each added
    # against a recorded case.

    return frozenset(found)


# Separable phrasal forms a flat substring list cannot express, because the
# object sits BETWEEN the two words: "mark the reminder done", "take bread off
# the grocery note", "check the milk off". `tool_mutation` grew one of these
# (_TAKE_OFF_OUT_RE) after a live false refusal; these are the same shape.
_SEPARABLE_COMPLETE_RE = re.compile(
    r"\b(?:mark|tick|check|cross)\b(?:\s+\S+){0,4}\s+(?:done|complete[d]?|off|out)\b",
    re.IGNORECASE,
)
_SEPARABLE_REMOVE_RE = re.compile(
    r"\btake\b(?:\s+\S+){0,4}\s+(?:off|out)\b",
    re.IGNORECASE,
)

# "Set a reminder to call the vet at 5pm", "put a timer on for ten minutes",
# "make me an appointment" — the VERB ("set", "put", "make") names an update or
# a placement, and the thing that makes these creations is the INDEFINITE
# OBJECT: a/an/another/new + a noun for a thing that can be created. Found by
# the very first live journey turn, which the verb table refused as
# "operation_not_requested_by_message" — "Set a reminder…" is how a person
# asks for a reminder, and no amount of adding verbs fixes that, because "set"
# genuinely is an update verb. This is the shape, not another word.
_CREATABLE_NOUNS = (
    "reminder", "reminders", "alarm", "alarms", "timer", "timers", "note",
    "notes", "event", "events", "meeting", "meetings", "task", "tasks",
    "entry", "entries", "item", "items", "list", "lists", "appointment",
    "appointments", "appt", "order", "orders", "goal", "goals",
)
_CREATE_NEW_OBJECT_RE = re.compile(
    r"\b(?:a|an|another|new|one)\s+(?:\w+\s+){0,2}(?:"
    + "|".join(_CREATABLE_NOUNS) + r")\b",
    re.IGNORECASE,
)

def unresolved_imperative(message: str) -> bool:
    """True when the turn is plainly an instruction about one of David's own
    objects, and the application cannot tell WHICH operation it names.

    This is the honest remainder after the wildcard fallback was removed: the
    request is real, so refusing it silently is wrong, and guessing among five
    effects is worse. `decide()` turns this into a CLARIFY.
    """
    normalized = _normalize(message)
    if not normalized.strip():
        return False
    if requested_operations(message) - {OperationKind.READ}:
        return False  # the operation IS identified; nothing unresolved here
    low_full = normalized.lower()
    for sentence, start in _sentences_with_offsets(normalized):
        low = sentence.lower()
        if not sentence.strip():
            continue
        if _inside_quotes(low_full, start) or _REPORTING_VERB_RE.search(low):
            continue
        if _CONDITIONAL_RE.search(low) or _HYPOTHETICAL_RE.search(low):
            continue
        if _looks_like_question(sentence) and not _REQUEST_FRAME_RE.search(low):
            continue
        if _is_negated(low):
            continue
        if _is_imperative_shape(low) and _REFERENCE_MARKER_RE.search(low):
            return True
    return False


_CLAUSE_BREAK_RE = re.compile(r"[,;]| but | however | although | yet ")
_NEGATION_MARKERS = (
    "don't", "do not", "doesn't", "does not", "didn't", "did not",
    "won't", "will not", "wouldn't", "would not", "shouldn't", "should not",
    "never", "no need to", "not going to", "not gonna", "can't", "cannot",
    "can not", "rather not", "instead of",
)


def _clause_before(low: str, pos: int) -> str:
    parts = _CLAUSE_BREAK_RE.split(low[:pos])
    return parts[-1] if parts else low[:pos]


def _is_negated(clause: str) -> bool:
    return any(neg in clause for neg in _NEGATION_MARKERS)


# ---------------------------------------------------------------------------
# What does a tool call DO?
# ---------------------------------------------------------------------------
#
# Derived from the tool's own name and arguments, so a newly registered tool
# is classified without an edit here. Explicit overrides exist only where the
# name genuinely misleads.

_KIND_TOKENS: Tuple[Tuple[OperationKind, FrozenSet[str]], ...] = (
    (OperationKind.RECURRING, frozenset({"standing"})),
    (OperationKind.DELETE, frozenset({"delete", "remove", "purge", "teardown"})),
    (OperationKind.CANCEL, frozenset({"cancel", "abort", "stop", "disable", "deactivate"})),
    (OperationKind.COMPLETE, frozenset({"complete", "resolve", "finish", "check", "close", "archive"})),
    (OperationKind.RESCHEDULE, frozenset({"reschedule", "postpone", "move"})),
    (OperationKind.UPDATE, frozenset({"edit", "update", "modify", "rename", "correct", "adjust", "merge", "set", "activate", "insert", "connect", "disconnect", "assign", "clear", "hide", "show"})),
    (OperationKind.CREATE, frozenset({"create", "add", "start", "log", "save", "schedule", "generate", "dispatch", "queue", "propose", "submit", "write", "send", "post", "react", "run", "extract", "arrange", "record", "made", "acknowledge", "confirm", "resume", "focus", "type", "open", "import", "explode"})),
    (OperationKind.CONTROL, frozenset({"control", "scene", "lock", "light", "climate", "cover", "media", "switch"})),
)

#: The LAST token of a tool name is its verb, in this codebase's naming. A
#: read whose name happens to contain a write-ish word earlier
#: (`food_log_search`, `food_log_summary`) is still a read, and classifying it
#: as a write means it needs action evidence to run — on the exact turn David is
#: asking a question. Found by the registry audit: `food_log_search`,
#: `food_log_summary`, `email_recent`, `training_schedule` and `weather` were
#: all classified as writes.
_READ_SUFFIXES: FrozenSet[str] = frozenset({
    "search", "list", "view", "get", "read", "status", "stats", "summary",
    "recent", "history", "details", "find", "query", "explain", "verify",
    "availability", "overview", "report", "timeseries", "insights",
    "correlation", "gaps", "anchors", "domains", "clusters", "state",
})

_EXPLICIT_KIND: Dict[str, OperationKind] = {
    # Reads whose names carry a mutating-looking token.
    "verify_action": OperationKind.READ,
    "training_schedule": OperationKind.READ,   # reads the schedule; "schedule" is the noun
    "weather": OperationKind.READ,             # no verb at all; defaulted to write
    "morning_brief": OperationKind.READ,
    "meeting_prep": OperationKind.READ,
    "suggest_next_task": OperationKind.READ,
    "why_did_you_notify": OperationKind.READ,
    "get_self_knowledge": OperationKind.READ,
    "calendar_find_availability": OperationKind.READ,
    "check_current_state": OperationKind.READ,
    "list_check": OperationKind.COMPLETE,      # actually ticks an item off
    "home_status": OperationKind.READ,
    "home_get_devices": OperationKind.READ,
    "home_list_scheduled": OperationKind.READ,
    "recipes_log_made": OperationKind.CREATE,
    "action_undo": OperationKind.UPDATE,
    "acknowledge_notifications": OperationKind.UPDATE,
    "find_tools": OperationKind.READ,
    "get_tool_result_details": OperationKind.READ,
    # Capture: additive by nature, never destructive. The convention work
    # established these as authorized by a disclosure rather than an
    # imperative; that survives here as a KIND, not as a bypass.
    "notes_create": OperationKind.CAPTURE,
    "notes_create_folder": OperationKind.CAPTURE,
    "fitness_note_create": OperationKind.CAPTURE,
    "remember_about_david": OperationKind.CAPTURE,
    # Physical/external effects.
    "home_light_control": OperationKind.CONTROL,
    "home_lock_control": OperationKind.CONTROL,
    "home_switch_control": OperationKind.CONTROL,
    "home_climate_control": OperationKind.CONTROL,
    "home_cover_control": OperationKind.CONTROL,
    "home_media_control": OperationKind.CONTROL,
    "home_scene_activate": OperationKind.CONTROL,
    "home_all_lights_off": OperationKind.CONTROL,
    "device_send_notification": OperationKind.CONTROL,
    "standing_order_create": OperationKind.RECURRING,
    "home_schedule_action": OperationKind.CREATE,
    # --- Major plan changes (FITNESS_COACH_IMPLEMENTATION_PLAN Step 21.5) ---
    #
    # These classified as UPDATE by name shape ("activate", "end"), which is
    # the one kind a bare CORRECTION can authorize. So "make that the
    # hypertrophy one" would have switched the athlete's entire training
    # plan on a phrasing the contract reads as a fix to a previous
    # statement — the same class of error as a reschedule request
    # authorizing a cancellation.
    #
    # Activating a program or a phase installs a plan that every downstream
    # reader follows until it is changed again: the dashboard's targets, the
    # scheduled sessions, the brief, the weekly report and the coach's own
    # state. That is standing authority, which is what RECURRING means here,
    # and it needs an instruction or an explicit confirmation.
    "program_activate": OperationKind.RECURRING,
    "phase_activate": OperationKind.RECURRING,
    # Ending a block early stops something that was scheduled to keep
    # running. "Cancel" and "end" are one intent with two implementations.
    "phase_end_block": OperationKind.CANCEL,
    # Inserting a block brings a new training period into being rather than
    # editing a field of an existing one.
    "phase_insert_block": OperationKind.CREATE,
    # Requesting a review creates a durable row and queues a model call, so
    # it is a CREATE — not the READ its name's "review"/"coach" tokens would
    # otherwise give it.
    "fitness_coach_review_request": OperationKind.CREATE,
    # Deciding a recommendation applies a target change the athlete eats
    # against. CONFIRMATION or an explicit instruction, never a correction.
    "fitness_recommendation_decide": OperationKind.RECURRING,
}

#: `notes_edit`-shaped tools: the kind depends on WHICH argument was passed.
#: An append cannot lose anything that already exists; `content`/`title`/
#: `remove_text` can.
_ARGUMENT_SENSITIVE: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    # tool: (additive-only args, destructive-or-rewriting args)
    "notes_edit": (("append_text",), ("content", "title", "remove_text")),
    "fitness_note_edit": (("append_text",), ("content", "title", "remove_text")),
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(name: str) -> FrozenSet[str]:
    return frozenset(_TOKEN_RE.findall((name or "").lower()))


def operation_kind_for(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> OperationKind:
    """What this specific call would do.

    Falls back to READ only for names that carry a read token and no
    mutating token — `tool_mutation.is_mutating_tool` stays the authority on
    that distinction so the two boundaries can never disagree about whether
    a tool is a write at all.
    """
    name = tool_name or ""
    if name in _ARGUMENT_SENSITIVE:
        additive, destructive = _ARGUMENT_SENSITIVE[name]
        args = arguments if isinstance(arguments, dict) else None
        if args is None:
            # Unparseable arguments are never treated as the safe shape.
            return OperationKind.UPDATE
        if any(args.get(k) for k in destructive):
            return OperationKind.UPDATE
        if any(isinstance(args.get(k), str) and args[k].strip() for k in additive):
            return OperationKind.CAPTURE
        return OperationKind.UPDATE

    if name in _EXPLICIT_KIND:
        return _EXPLICIT_KIND[name]

    from app.services.tool_mutation import is_mutating_tool

    if not is_mutating_tool(name):
        return OperationKind.READ

    # A name whose final token is a read verb is a read, whatever appears
    # earlier in it. `food_search_and_log` still ends in "log" and stays a
    # write, which is the distinction that makes this safe.
    tail = name.lower().rsplit("_", 1)[-1]
    if tail in _READ_SUFFIXES:
        return OperationKind.READ

    toks = _tokens(name)
    for kind, kind_tokens in _KIND_TOKENS:
        if toks & kind_tokens:
            return kind
    # A mutating tool whose name names no recognizable operation is treated
    # as an UPDATE: target-bound, so it must resolve a target and be
    # requested — the conservative direction for an unknown write.
    return OperationKind.UPDATE


# ---------------------------------------------------------------------------
# The authority matrix
# ---------------------------------------------------------------------------
#
# Which utterance classes can authorize which operation kinds. This is the
# whole policy in one readable table — the thing eleven scattered guard
# clauses could not be read as.

_AUTHORITY: Dict[OperationKind, FrozenSet[UtteranceClass]] = {
    OperationKind.READ: frozenset(UtteranceClass),  # a read needs no authority
    OperationKind.CAPTURE: frozenset({
        UtteranceClass.CAPTURE, UtteranceClass.INSTRUCTION,
        UtteranceClass.CORRECTION, UtteranceClass.SOCIAL,
        UtteranceClass.CONFIRMATION,
    }),
    OperationKind.CREATE: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
    OperationKind.UPDATE: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CORRECTION,
        UtteranceClass.CONFIRMATION,
    }),
    OperationKind.RESCHEDULE: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CORRECTION,
        UtteranceClass.CONFIRMATION,
    }),
    OperationKind.COMPLETE: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
    OperationKind.CANCEL: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
    OperationKind.DELETE: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
    OperationKind.RECURRING: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
    OperationKind.CONTROL: frozenset({
        UtteranceClass.INSTRUCTION, UtteranceClass.CONFIRMATION,
    }),
}


# ---------------------------------------------------------------------------
# Request / decision types
# ---------------------------------------------------------------------------


#: The one narrow set of write tools that stay available regardless of what
#: the turn was — carried over verbatim from
#: `tool_mutation.ALWAYS_ALLOWED_MUTATING`, whose reason still holds: marking
#: a notification read on a bare "Good morning Sara" is housekeeping David
#: cannot sensibly be asked to authorize, and it destroys nothing. Kept as an
#: explicit name list rather than a rule, so adding to it is a visible edit.
ALWAYS_ALLOWED_TOOLS: FrozenSet[str] = frozenset({"acknowledge_notifications"})


class Verdict(str, Enum):
    ALLOW = "allow"
    CLARIFY = "clarify"   # a genuine ambiguity: ask, do not guess
    REFUSE = "refuse"


@dataclass(frozen=True)
class ResolvedTarget:
    """One owner-verified object a target-bound operation would act on."""

    domain: str
    target_id: str
    label: str = ""
    revision: Optional[str] = None


@dataclass(frozen=True)
class TargetResolution:
    """The result of resolving a reference once, owner-scoped.

    `named` is the target the CALL named (from its arguments). `candidates`
    are the owner's rows the user's WORDS could mean. Authorization needs
    both to agree.
    """

    named: Optional[ResolvedTarget] = None
    candidates: Tuple[ResolvedTarget, ...] = ()
    owner_mismatch: bool = False
    not_found: bool = False
    unresolvable: bool = False  # no resolver for this domain (documented gap)
    #: Does the message name this domain's own noun ("reminder", "note")?
    #: J10's mechanism exactly: "stop reminding me about it" contains no
    #: reminder NOUN, and must not authorize cancelling a real reminder.
    domain_referenced: bool = False
    #: Do the named target's own distinctive words appear in the message?
    #: "Scratch the vet one" against a row titled "Vet appointment" — this is
    #: what authorizes a reference that names no domain noun at all.
    label_referenced: bool = False


@dataclass(frozen=True)
class OperationRequest:
    """The structured operation the application validates and executes.

    Field names follow the plan's suggested shape, adapted to the existing
    types. `owner_id` is never taken from a model argument.
    """

    request_id: str
    conversation_id: Optional[str]
    owner_id: str
    tool_name: str
    arguments: Dict[str, Any]
    operation_kind: OperationKind
    domain: str
    argument_source: str = "model"       # "model" | "proposal" | "user"
    target_reference: Optional[str] = None
    proposal_id: Optional[str] = None
    operation_id: Optional[str] = None
    expected_revision: Optional[str] = None


@dataclass(frozen=True)
class TurnContext:
    """Everything about the turn the decision may consider. No model output."""

    turn_message: str
    utterance: UtteranceClass
    requested: FrozenSet[OperationKind]
    last_turn_mutating_tools: Tuple[str, ...] = ()
    #: The turn is an instruction about one of his objects, and which operation
    #: it names cannot be identified. Produces a CLARIFY, never a grant.
    unresolved_imperative: bool = False
    proposal_authorized: bool = False
    proposal_operation_kind: Optional[OperationKind] = None
    proposal_source_message: str = ""

    @classmethod
    def build(
        cls,
        turn_message: str,
        last_turn_mutating_tools: Sequence[str] = (),
        proposal_authorized: bool = False,
        proposal_operation_kind: Optional[OperationKind] = None,
        proposal_source_message: str = "",
    ) -> "TurnContext":
        return cls(
            turn_message=turn_message or "",
            utterance=classify_utterance(turn_message),
            requested=requested_operations(turn_message),
            unresolved_imperative=unresolved_imperative(turn_message or ""),
            last_turn_mutating_tools=tuple(last_turn_mutating_tools or ()),
            proposal_authorized=proposal_authorized,
            proposal_operation_kind=proposal_operation_kind,
            proposal_source_message=proposal_source_message or "",
        )


@dataclass(frozen=True)
class OperationDecision:
    """Structured, auditable outcome. Argument VALUES never appear in
    `reason` or `detail` — only argument names and resolved ids."""

    verdict: Verdict
    reason: str
    operation_kind: OperationKind
    utterance: UtteranceClass
    domain: str
    resolved_target_ids: Tuple[str, ...] = ()
    candidate_ids: Tuple[str, ...] = ()
    detail: str = ""
    argument_names: Tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    def as_log_record(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "operation": self.operation_kind.value,
            "utterance": self.utterance.value,
            "domain": self.domain,
            "targets": list(self.resolved_target_ids),
            "candidates": list(self.candidate_ids),
            "arguments": list(self.argument_names),
            "detail": self.detail,
        }


# Reason codes. Stable strings so the decision log and the tests agree.
R_READ_ONLY = "read_only_operation"
R_AUTHORIZED_BY_UTTERANCE = "authorized_by_utterance"
R_AUTHORIZED_BY_PROPOSAL = "authorized_by_pending_proposal"
R_AUTHORIZED_BY_CONTINUATION = "authorized_by_continuation"
R_NO_AUTHORITY_FOR_CLASS = "utterance_class_cannot_authorize_operation"
R_OPERATION_NOT_REQUESTED = "operation_not_requested_by_message"
R_CORRECTION_IS_NOT_DELETION = "correction_does_not_authorize_destruction"
R_NO_RECURRING_SCOPE = "no_recurring_scope_in_request"
R_OWNER_MISMATCH = "target_belongs_to_another_owner"
R_TARGET_AMBIGUOUS = "reference_matches_multiple_targets"
R_TARGET_NOT_REFERENCED = "named_target_not_referenced_by_message"
R_TARGET_UNRESOLVED = "target_not_resolvable"
R_PROPOSAL_KIND_MISMATCH = "proposal_was_for_a_different_operation"
R_OPERATION_UNCLEAR = "instruction_names_no_identifiable_operation"


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------
#
# One domain name per kind of thing, shared by the decision record, the
# owner-scoped resolver (`reference_resolution.DOMAIN_SPECS`) and read-cache
# invalidation (`session_cache`). Before this, each of those derived a domain
# its own way: `_tool_domain_stem` strips scope-sensitive verbs, so it returns
# "reminders" for `reminders_cancel` and "calendar_create" for
# `calendar_create` — fine for the one question it was written for, useless as
# a shared key. A write and the read it must invalidate have to agree on the
# name, or a stale read survives the write that contradicts it (finding 22).
#
# Longest-prefix match against an explicit table, falling back to the tool
# name's first token. Explicit because the mapping is genuinely irregular:
# `workout_log_create` and `template_update` are both fitness; `list_add` and
# `daily_task_create` are different domains that both start with a list-ish
# word.
_DOMAIN_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("daily_task", "daily_task"),
    ("cancel_research_plan", "research_plan"),
    ("create_research_plan", "research_plan"),
    ("research_plan", "research_plan"),
    ("notes", "notes"),
    ("merge_notes", "notes"),
    ("find_similar_notes", "notes"),
    ("canvas_save_as_note", "notes"),
    ("remember_about_david", "personal_knowledge"),
    ("query_david_knowledge", "personal_knowledge"),
    ("reminders", "reminders"),
    ("location_reminder", "reminders"),
    ("timers", "timers"),
    ("calendar", "calendar"),
    ("meeting_prep", "calendar"),
    ("list_add", "list"),
    ("list_remove", "list"),
    ("list_check", "list"),
    ("list_view", "list"),
    ("food", "food"),
    ("recipes", "recipes"),
    ("nutrition_guide", "fitness"),
    ("workout", "fitness"),
    ("fitness", "fitness"),
    ("template", "fitness"),
    ("program", "fitness"),
    ("phase", "fitness"),
    ("recovery_log", "fitness"),
    ("training_schedule", "fitness"),
    ("home", "home"),
    ("standing_order", "automation"),
    ("learning", "learning"),
    ("documents", "documents"),
    ("document_generate", "documents"),
    ("artifact_read", "documents"),
    ("files_to_studio", "documents"),
    ("memory_search", "memory"),
    ("email", "email"),
    ("inbox", "email"),
    ("map", "map"),
    ("resolve_thread", "thread"),
    ("manage_goal", "goals"),
    ("scratchpad", "scratchpad"),
    ("places", "places"),
    ("chess", "chess"),
    ("dispatch", "background"),
    ("get_agent_status", "background"),
    ("cancel_agent_task", "background"),
    ("get_background_tasks", "background"),
)


def domain_for_tool(tool_name: str) -> str:
    """The shared domain name for a tool. Never raises; unknown tools get
    their own first token, which is stable and unique enough to key a cache
    and a log record even when no resolver exists for it."""
    name = (tool_name or "").lower()
    best_prefix = ""
    best_domain = ""
    for prefix, domain in _DOMAIN_PREFIXES:
        if name.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix, best_domain = prefix, domain
    if best_domain:
        return best_domain
    return name.split("_")[0] or "unknown"


def _domain_for(tool_name: str) -> str:
    return domain_for_tool(tool_name)


def build_request(
    *,
    request_id: str,
    conversation_id: Optional[str],
    owner_id: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    argument_source: str = "model",
    proposal_id: Optional[str] = None,
    operation_id: Optional[str] = None,
) -> OperationRequest:
    args = arguments if isinstance(arguments, dict) else {}
    return OperationRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        owner_id=owner_id,
        tool_name=tool_name,
        arguments=args,
        operation_kind=operation_kind_for(tool_name, args),
        domain=_domain_for(tool_name),
        argument_source=argument_source,
        proposal_id=proposal_id,
        operation_id=operation_id,
        expected_revision=args.get("base_revision") if isinstance(args, dict) else None,
    )


def decide(
    request: OperationRequest,
    ctx: TurnContext,
    resolution: Optional[TargetResolution] = None,
) -> OperationDecision:
    """The single authorization decision. Pure: no DB, no I/O, no model.

    `resolution` is supplied by the caller (see `reference_resolution.
    resolve_for_request`) so this stays unit-testable and so the SAME
    resolution can be reused for execution and receipts rather than resolved
    again — plan C2's "resolve each reference once per operation".
    """
    kind = request.operation_kind
    arg_names = tuple(sorted(request.arguments.keys()))

    def decision(verdict: Verdict, reason: str, *, detail: str = "",
                 targets: Sequence[str] = (), candidates: Sequence[str] = ()) -> OperationDecision:
        return OperationDecision(
            verdict=verdict, reason=reason, operation_kind=kind,
            utterance=ctx.utterance, domain=request.domain,
            resolved_target_ids=tuple(targets), candidate_ids=tuple(candidates),
            detail=detail, argument_names=arg_names,
        )

    # 1. A read needs no authority at all. This is deliberately first: the
    # single worst live failure mode of the old boundary was refusing
    # `query_david_knowledge` on a plain recall question.
    if kind is OperationKind.READ:
        return decision(Verdict.ALLOW, R_READ_ONLY)

    # 2. A consumed pending proposal carries its own authority — but only for
    # the operation kind that was actually proposed. A scoped "yes" confirms
    # THAT proposal, not any write.
    if request.argument_source == "proposal" and ctx.proposal_authorized:
        if ctx.proposal_operation_kind is not None and ctx.proposal_operation_kind is not kind:
            return decision(
                Verdict.REFUSE, R_PROPOSAL_KIND_MISMATCH,
                detail=f"proposal was {ctx.proposal_operation_kind.value}, call is {kind.value}",
            )
        if kind is OperationKind.RECURRING:
            from app.services.tool_mutation import has_recurring_scope
            if not (has_recurring_scope(ctx.turn_message)
                    or has_recurring_scope(ctx.proposal_source_message)):
                return decision(Verdict.REFUSE, R_NO_RECURRING_SCOPE)
        return _check_target(request, ctx, resolution, decision,
                             authorized_reason=R_AUTHORIZED_BY_PROPOSAL)

    # 3a. Two checks run BEFORE the generic authority table, purely so the
    # refusal carries the reason that actually explains itself. Both would
    # also be caught below; "a correction is not a deletion" and "you asked
    # for this once, not every time" are what Sara can say to David, and
    # "a correction cannot authorize a cancel" is not.
    if ctx.utterance is UtteranceClass.CORRECTION and kind in DESTRUCTIVE_KINDS:
        return decision(Verdict.REFUSE, R_CORRECTION_IS_NOT_DELETION)

    # An elliptical follow-up inherits the operation from the turn that just
    # ran it: "And one for the dentist on October 2nd at 9am" after a reminder
    # was created is a second reminder, and it names no operation at all.
    # Computed here because it has to satisfy BOTH the class check and the
    # requested-operation check below. Restricted to the SAME tool that
    # actually executed last turn, so it can never escalate to something David
    # did not just have done.
    _elliptical_ok = (
        request.tool_name in ctx.last_turn_mutating_tools
        and is_elliptical_continuation(ctx.turn_message)
    )

    # 3b. Does this utterance class have any authority over this kind?
    allowed_classes = _AUTHORITY.get(kind, frozenset())
    if ctx.utterance not in allowed_classes and not _elliptical_ok:
        # A continuation of a mutating tool that actually executed last turn
        # is the one narrow exception, preserved from the existing boundary.
        if (request.tool_name in ctx.last_turn_mutating_tools
                and ctx.utterance is UtteranceClass.CONFIRMATION):
            return _check_target(request, ctx, resolution, decision,
                                 authorized_reason=R_AUTHORIZED_BY_CONTINUATION)
        return decision(
            Verdict.REFUSE, R_NO_AUTHORITY_FOR_CLASS,
            detail=f"{ctx.utterance.value} cannot authorize {kind.value}",
        )

    # 4. A standing order needs its own recurring evidence, over and above a
    # one-time request (finding J11). Checked here — after the class check, so
    # a hypothetical is refused for being a hypothetical, and before the
    # requested-operation check, so "turn on the porch light" gets the reason
    # that actually helps Sara answer ("he asked for this once, not every
    # time") rather than a generic operation mismatch.
    #
    # Skipped for a continuation: the tool actually EXECUTED last turn, which
    # means this exact check already ran and passed then, and a confirming
    # "yes" is never where the recurring language would live.
    via_continuation = (
        request.tool_name in ctx.last_turn_mutating_tools
        and ctx.utterance is UtteranceClass.CONFIRMATION
    )
    if kind is OperationKind.RECURRING and not via_continuation:
        from app.services.tool_mutation import has_recurring_scope
        if not has_recurring_scope(ctx.turn_message):
            return decision(Verdict.REFUSE, R_NO_RECURRING_SCOPE)

    # 5. Did the user's own words request THIS operation? This is the check
    # the old boolean could not express: "move the vet one to seven"
    # authorizes a reschedule and not a cancellation.
    #
    # Exempted: CAPTURE (the disclosure is the request — a capture verb is
    # not required and demanding one refused 7 of 9 realistic phrasings) and
    # CONFIRMATION/ACKNOWLEDGEMENT-class turns, which carry no verbs of their
    # own and are handled by the proposal/continuation paths above.
    # A CORRECTION is its own request for the corresponding change, the same
    # way a disclosure is its own request for a capture: "Actually Priya is at
    # Initech" carries no update verb at all, and the plan requires it to
    # correct the clearly referenced fact. It still cannot authorize a
    # destructive kind — that is checked above, before this.
    _correction_implies = (
        ctx.utterance is UtteranceClass.CORRECTION
        and kind in (OperationKind.UPDATE, OperationKind.RESCHEDULE)
    )
    if (kind is not OperationKind.CAPTURE and not _correction_implies
            and not _elliptical_ok and ctx.utterance not in (
                UtteranceClass.CONFIRMATION, UtteranceClass.ACKNOWLEDGEMENT,
            )):
        if not (ctx.requested & _SATISFIED_BY.get(kind, frozenset({kind}))):
            # An imperative about one of his own objects whose operation the
            # application cannot identify is a real request it cannot safely
            # execute. Asking is the correct third answer — it is what replaced
            # the wildcard that used to grant five kinds at once.
            if ctx.unresolved_imperative and kind in TARGET_BOUND_KINDS:
                return decision(
                    Verdict.CLARIFY, R_OPERATION_UNCLEAR,
                    detail="an instruction whose operation is not identifiable",
                )
            return decision(
                Verdict.REFUSE, R_OPERATION_NOT_REQUESTED,
                detail=f"message supports {sorted(k.value for k in ctx.requested)}",
            )

    return _check_target(request, ctx, resolution, decision,
                         authorized_reason=R_AUTHORIZED_BY_UTTERANCE)


def _check_target(
    request: OperationRequest,
    ctx: TurnContext,
    resolution: Optional[TargetResolution],
    decision: Callable[..., OperationDecision],
    *,
    authorized_reason: str,
) -> OperationDecision:
    """Target binding for the kinds whose effect lands on one existing row.

    Order of severity is deliberate:
      * another owner's row → REFUSE, never any fallback;
      * the user's words match several of their own rows → CLARIFY, which is
        an answer David can act on, not a silent guess;
      * the call names a row the words never referenced → REFUSE;
      * no resolver for this domain, or the named id resolves to nothing →
        ALLOW and let the tool fail honestly with "not found". Blocking here
        would manufacture false refusals, which is the failure the R01 round-4
        work explicitly documented and chose against.
    """
    kind = request.operation_kind
    if kind not in TARGET_BOUND_KINDS:
        return decision(Verdict.ALLOW, authorized_reason)

    if resolution is None:
        return decision(Verdict.ALLOW, authorized_reason, detail="no resolution supplied")

    if resolution.owner_mismatch:
        return decision(Verdict.REFUSE, R_OWNER_MISMATCH)

    named = resolution.named
    candidates = resolution.candidates

    if named is not None:
        candidate_ids = {c.target_id for c in candidates}
        # Several of David's own rows match his reference equally well, and the
        # call picked one of them. Found live: "Cancel the plant one." with both
        # "Water the plants" and "Repot the plant in the office" pending —
        # cancelling either is a guess, and the one it guessed was wrong. For a
        # destructive or completing operation the answer is to ask; for an
        # update or a reschedule it is not, because naming the wrong one there
        # is recoverable and refusing every such call would make ordinary
        # multi-item domains unusable.
        if len(candidate_ids) > 1 and kind in (
            DESTRUCTIVE_KINDS | {OperationKind.COMPLETE}
        ):
            return decision(
                Verdict.CLARIFY, R_TARGET_AMBIGUOUS,
                targets=(named.target_id,), candidates=sorted(candidate_ids),
                detail=(
                    f"{len(candidate_ids)} of David's own rows match the reference "
                    f"equally well"
                ),
            )
        if candidate_ids and named.target_id not in candidate_ids:
            if len(candidate_ids) > 1:
                return decision(
                    Verdict.CLARIFY, R_TARGET_AMBIGUOUS,
                    candidates=sorted(candidate_ids),
                    detail=f"{len(candidate_ids)} of David's own rows match the reference",
                )
            return decision(
                Verdict.REFUSE, R_TARGET_NOT_REFERENCED,
                targets=(named.target_id,), candidates=sorted(candidate_ids),
            )
        if not candidate_ids and kind in DESTRUCTIVE_KINDS:
            # The call names a real row of David's, but nothing in his words
            # matched it. Two very different situations, and the difference is
            # whether he referred to this KIND of thing at all:
            #
            #   "cancel the vet reminder"  — names the domain; the model may
            #       legitimately hold an id from a prior lookup whose title
            #       shares no words with his phrasing. Allow; the tool still
            #       fails honestly if the id is wrong.
            #   "close that thread and stop reminding me about it" — names no
            #       reminder NOUN and no reminder's words. Cancelling a real,
            #       unrelated reminder here is finding J10, reproduced in both
            #       trials. Refuse.
            if not (resolution.domain_referenced or resolution.label_referenced):
                return decision(
                    Verdict.REFUSE, R_TARGET_NOT_REFERENCED,
                    targets=(named.target_id,),
                    detail="message references neither this domain nor this row",
                )
        return decision(Verdict.ALLOW, authorized_reason, targets=(named.target_id,),
                        candidates=sorted(candidate_ids))

    # The call named no target id. If the reference resolves to exactly one
    # of David's rows, that IS the target; several means ask.
    if len(candidates) > 1:
        return decision(
            Verdict.CLARIFY, R_TARGET_AMBIGUOUS,
            candidates=[c.target_id for c in candidates],
            detail=f"{len(candidates)} of David's own rows match the reference",
        )
    if len(candidates) == 1:
        return decision(Verdict.ALLOW, authorized_reason,
                        targets=(candidates[0].target_id,))

    if resolution.unresolvable or resolution.not_found:
        return decision(Verdict.ALLOW, authorized_reason,
                        detail="target unresolved here; the tool reports not-found honestly")
    return decision(Verdict.ALLOW, authorized_reason)


# ---------------------------------------------------------------------------
# Round-level check: several targets of the same operation in one turn
# ---------------------------------------------------------------------------


def find_unauthorized_multi_target_calls(
    tool_calls: Sequence[Dict[str, Any]],
    message: str,
    prior_attempts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Tool-call ids to withhold because the model reached for a SECOND
    distinct target of the same destructive operation without the user
    authorizing more than one.

    Kept as a thin wrapper over `tool_mutation.find_ambiguous_same_turn_
    removals` rather than reimplemented: that function is already correct for
    exactly this shape, already covers the cross-round case, and is already
    independently tested. What changes is only that the contract now owns the
    call site, so there is one place a decision about a turn is made.
    """
    from app.services.tool_mutation import find_ambiguous_same_turn_removals

    return find_ambiguous_same_turn_removals(tool_calls, message, prior_attempts=prior_attempts)


#: What makes a correction a REQUEST: something to correct to.
_CORRECTION_CARRIES_A_VALUE_RE = re.compile(
    r"\bnot\b|\binstead\b|\brather\s+than\b|\bmeant\b|\bshould\s+(?:be|say)\b"
    r"|\bmake\s+(?:it|that)\b|\d|[\"“”]",
    re.IGNORECASE,
)

#: Utterance classes whose own words can ask for a change.
_MUTATION_REQUESTING_CLASSES: FrozenSet[UtteranceClass] = frozenset({
    UtteranceClass.INSTRUCTION,
    UtteranceClass.CORRECTION,
})


def turn_requests_a_mutation(message: str) -> bool:
    """Did this turn ASK for something to change?

    Used by `outcome_grounding.ground_reply` to catch the case no claim pattern
    can: a requested change, no tool call at all, and a reply that reads as
    though it happened. Deliberately conservative — a question, a hypothetical,
    an acknowledgement, a bare confirmation and ordinary conversation are all
    False, so an ordinary turn is never subjected to this check.
    """
    utterance = classify_utterance(message)
    if utterance is UtteranceClass.CORRECTION and not _CORRECTION_CARRIES_A_VALUE_RE.search(
        _normalize(message)
    ):
        # A correction with nothing to correct TO is not a request to change a
        # record. Belt and braces for the classifier: even if something is
        # misread as a correction, it only reaches the grounding check when it
        # names a replacement — a contrast ("not X", "instead of") or a value.
        return False
    if utterance is UtteranceClass.CORRECTION:
        # A correction always asks for the record to change; that is what makes
        # it a correction, and it is why `decide` grants UPDATE for one without
        # needing an update verb. Its `requested_operations` set is empty by
        # design ("That was actually 150 grams, not 100." contains no verb at
        # all), so requiring one here would miss exactly the live case this
        # check exists for.
        return True
    if utterance is not UtteranceClass.INSTRUCTION:
        return False
    return bool(requested_operations(message) - {OperationKind.READ})


def selection_kinds_for_message(
    message: str, last_turn_mutating_tools: Sequence[str] = (),
) -> FrozenSet[OperationKind]:
    """Which operation kinds a tool MENU may reasonably offer for this turn.

    Selection is an aid, not the authorization boundary — but the plan is
    equally explicit that "routing must not silently make a supported action
    impossible", and that is exactly what happened when `gate_mutating_tools`'s
    verb lexicon met an elliptical follow-up: the boundary would have authorized
    "And one for the dentist on October 2nd at 9am", and the menu never offered
    `reminders_create`, so Sara told David she had no way to set reminders.
    Found live, twice, in two different shapes.

    So selection now reads the same classification the boundary does. It stays
    deliberately WIDER than `decide()` — no target resolution, no proposal
    state, arguments unknown — because offering a tool costs nothing and
    withholding one costs a capability.
    """
    utterance = classify_utterance(message)
    if utterance is UtteranceClass.CONFIRMATION:
        # Only what actually ran last turn, plus reads. A bare "yes, do it" with
        # nothing to continue offers nothing, and a confirmation of one
        # operation does not put an unrelated write on the wire — both pinned by
        # existing tests, and both right: the boundary's proposal machinery is
        # scoped to a specific tool, so widening the MENU here would only make
        # it possible for the model to reach for something else entirely.
        allowed = {OperationKind.READ}
        for name in last_turn_mutating_tools or ():
            allowed.add(operation_kind_for(name, None))
        return frozenset(allowed)
    if utterance in (UtteranceClass.ACKNOWLEDGEMENT, UtteranceClass.HYPOTHETICAL,
                     UtteranceClass.REPORTED, UtteranceClass.QUESTION):
        allowed = {OperationKind.READ}
    elif utterance is UtteranceClass.CAPTURE:
        allowed = {OperationKind.READ, OperationKind.CAPTURE}
    elif utterance is UtteranceClass.CORRECTION:
        allowed = {OperationKind.READ, OperationKind.CAPTURE,
                   OperationKind.UPDATE, OperationKind.RESCHEDULE}
    else:  # INSTRUCTION, SOCIAL
        requested = requested_operations(message)
        allowed = {OperationKind.READ, OperationKind.CAPTURE}
        for kind, satisfiers in _SATISFIED_BY.items():
            if requested & satisfiers:
                allowed.add(kind)

    # An elliptical follow-up may use the tools that actually ran last turn.
    if last_turn_mutating_tools and is_elliptical_continuation(message):
        for name in last_turn_mutating_tools:
            allowed.add(operation_kind_for(name, None))
    return frozenset(allowed)


def refusal_message(decision: OperationDecision, tool_name: str) -> str:
    """What the model is told when a call is withheld.

    Says WHY, in terms of what David actually said, and never implies the
    action happened. The old boundary returned one generic string for every
    refusal, which is why Sara could not tell David anything useful about a
    block ("system's being stickier than usual").
    """
    base = f"{tool_name} did not run"
    never_coach = (
        " Do not tell David to repeat himself, rephrase, or nudge you again, and "
        "do not say the system refused you — answer what he actually said."
    )
    if decision.verdict is Verdict.CLARIFY and decision.reason == R_OPERATION_UNCLEAR:
        return (
            f"{base} — David clearly wants something done to that, but the word he "
            f"used doesn't tell me WHICH thing (cancel it? mark it done? change it?), "
            f"and guessing among those could remove something. Ask him which, naming "
            f"the options. Do not describe anything as done." + never_coach
        )
    if decision.verdict is Verdict.CLARIFY:
        n = len(decision.candidate_ids)
        return (
            f"{base} — \"{decision.domain}\" reference matches {n} different things "
            f"David owns, so acting would be a guess. Ask him which one he means, "
            f"naming them. Do not describe anything as done."
        )
    reasons = {
        R_NO_AUTHORITY_FOR_CLASS: (
            f"{base} — David's message is a {decision.utterance.value}, not a request to "
            f"{decision.operation_kind.value} anything. Answer what he actually said. "
            "Do not describe the action as done, and do not coach him on how to word it."
        ),
        R_OPERATION_NOT_REQUESTED: (
            f"{base} — David asked for something else in this message "
            f"({decision.detail}), not a {decision.operation_kind.value}. "
            "Do the thing he asked for instead. Do not describe this as done."
        ),
        R_CORRECTION_IS_NOT_DELETION: (
            f"{base} — he corrected a fact, which authorizes changing the record, not "
            "deleting or cancelling anything. Make the correction instead."
        ),
        R_NO_RECURRING_SCOPE: (
            f"{base} — he asked for a one-time action, not a recurring one. Nothing he "
            "said asks for this to repeat. Do it once with the direct tool, or ask him "
            "whether he wants it to become recurring. Do not describe a standing order "
            "as created."
        ),
        R_OWNER_MISMATCH: (
            f"{base} — that record is not David's. Nothing was changed. Say you could not "
            "find it among his."
        ),
        R_TARGET_NOT_REFERENCED: (
            f"{base} — the record it named is not the one David referred to. Look the right "
            "one up and confirm which he means. Do not describe anything as done."
        ),
        R_PROPOSAL_KIND_MISMATCH: (
            f"{base} — his \"yes\" confirmed a different action from this one. Ask him "
            "directly about this one before doing it."
        ),
    }
    return reasons.get(
        decision.reason,
        f"{base} — it was not authorized by this turn ({decision.reason}). "
        "Do not describe it as done.",
    ) + never_coach
