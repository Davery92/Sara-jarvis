"""Mutation gate for chat tool selection (SARA_CHAT_HARNESS_MTP_REPAIR Phase 5).

David's 2026-09-16 morning conversation: casual messages ("Good morning
Sara", "Shoulder workout was good") loaded mutating tools (notes_create,
list_add, reminders_create, workout write tools reached via semantic
retrieval) that had no business being on the wire — nothing in the message
asked Sara to do anything. Semantic proximity to a tool's description is not
evidence of intent to invoke it: "shoulder workout was good" is lexically
close to fitness-logging tools without being a request to log anything.

This module classifies tool names as mutating/read-only by a name-pattern
heuristic (no per-tool metadata exists in the registry) and detects whether
a message carries positive action evidence. `gate_mutating_tools` is applied
at the final tool-schema boundary in the chat turn: a mutating tool survives
only if the message has action evidence, the tool is already sticky (a prior
turn in this conversation already invoked it — continuation), or it's on the
small explicit always-allowed list (e.g. acknowledge_notifications).

Classification is intentionally conservative: an unrecognized tool name
defaults to "mutating" so retrieval noise never silently smuggles a write
tool past the gate. The cost of a false positive here is a missed retrieval,
not a wrong action.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Tokens that, if present anywhere in a snake_case tool name, mark it as
# having a side effect. Checked before READ_TOKENS so "food_search_and_log"
# (both "search" and "log") is classified mutating.
MUTATING_TOKENS = {
    "create", "add", "edit", "delete", "remove", "cancel", "update", "send",
    "schedule", "log", "check", "complete", "start", "end", "resign", "offer",
    "pause", "resume", "activate", "set", "merge", "write", "post", "control",
    "move", "run", "execute", "approve", "adjust", "dispatch", "fetch",
    "acknowledge", "confirm", "reset", "clear", "archive", "assign", "draft",
    "subscribe", "unsubscribe", "deactivate", "extract",
    # Added 2026-09-28 (reliable-assistant registry audit): `list_correct_item`
    # classified as READ-ONLY, because "list" is a read token and "correct" was
    # in neither set. A tool whose name says it corrects something is a write.
    "correct", "reschedule", "rename", "restore", "undo", "insert", "apply",
}

# Tokens that mark a tool as read-only *when no mutating token is present*.
READ_TOKENS = {
    "search", "list", "view", "get", "read", "details", "status", "stats",
    "summary", "history", "find", "discover", "analyze", "suggest", "review",
    "coach",
    # R03 (2026-09-26): verify_action only ever READS action_receipt rows —
    # without this it would default to mutating (unrecognized names default
    # mutating, deliberately conservative for write tools) and need its own
    # action evidence to survive the gate, defeating its purpose: the model
    # must be able to check a real record on its own initiative, the same
    # way it can search or list.
    "verify",
    # Live validation 2026-09-27, conversation B turn 2 ("What was I supposed
    # to do about the Contoso guy?"): `query_david_knowledge` was REFUSED by
    # the execution boundary as a mutating tool. Unrecognized names default to
    # mutating — deliberately conservative — but that default also catches
    # read-only tools whose names happen to use none of the listed read verbs,
    # and then a plain recall question cannot reach the very tool that answers
    # it. `query_david_knowledge` and `pattern_query` only ever SELECT;
    # `diagnostics_explain` only reads state. These are gated exactly when
    # David is asking a question, which is the worst possible time.
    #
    # Safe by construction: READ_TOKENS only decides a name that carries NO
    # mutating token at all (see is_mutating_tool), so this cannot un-gate a
    # "query_and_delete"-shaped name.
    "query",
    "explain",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(name: str) -> set:
    return set(_TOKEN_RE.findall(name.lower()))


# Names the token rules get WRONG, listed explicitly so the correction is a
# visible edit rather than a token added to a shared set.
#
# `fitness_coach_review_request` carries "review" and "coach", both read
# tokens, and no mutating one — so it classified read-only. It creates a
# durable `fitness_coach_review` row and queues a model call. Adding
# "request" to MUTATING_TOKENS instead would reclassify every future
# `*_request` name sight unseen, including read-only ones.
EXPLICIT_MUTATING = {
    "fitness_coach_review_request",
}

# And the reverse: names that carry a mutating token but only ever read.
EXPLICIT_READ_ONLY: set = set()


def is_mutating_tool(name: str) -> bool:
    """Conservative name-pattern classification: unrecognized -> mutating."""
    key = (name or "").strip()
    if key in EXPLICIT_MUTATING:
        return True
    if key in EXPLICIT_READ_ONLY:
        return False
    toks = _tokens(key)
    if toks & MUTATING_TOKENS:
        return True
    if toks & READ_TOKENS:
        return False
    return True


# Explicit, narrow exceptions that stay available regardless of action
# evidence (mirrors the plan's "narrowly justified notification
# acknowledgement path" for a bare "Good morning Sara").
ALWAYS_ALLOWED_MUTATING = {"acknowledge_notifications"}


# --- Capture is not an imperative (2026-09-27) ------------------------------
# The execution-boundary gate requires a verb from ACTION_INTENT_VERBS before
# any mutating tool may run. That is the right bar for a consequential action
# (a standing order, a cancellation, sending something), and the wrong bar for
# writing down what David just said. Measured against realistic phrasings for
# "capture a note about a person I just met", 7 of 9 were refused:
#
#   REFUSE  "Remember that I met Dana from Acme, she runs their platform team"
#   REFUSE  "Dana from Acme: platform team lead, wants a follow-up on pricing"
#   REFUSE  "Jot down that Marcus at Contoso is hiring two SREs"
#   REFUSE  "FYI I talked to Priya from Globex about the migration"
#   ALLOW   "Add a note that Dana runs the platform team"
#
# For a capture, the disclosure IS the request — there is no separate imperative
# to look for, and demanding one produces exactly the "I had to tell her twice"
# failure. These calls are additive (they create a new row or append to an
# existing one), user-visible in the notes UI, and trivially reversible, so the
# gate buys nothing here that is worth that cost. Note that this is narrower
# than ALWAYS_ALLOWED_MUTATING: only the ADDITIVE shape is exempt. A full
# content rewrite or a remove_text on an existing note still needs real action
# evidence, because those can destroy something.
CAPTURE_TOOLS = {
    "notes_create",
    "notes_create_folder",
    "fitness_note_create",
}

# Tools that can be called in a purely additive way, but also in a destructive
# way — so the exemption depends on the ARGUMENTS, not just the name.
APPEND_ONLY_CAPABLE = {"notes_edit", "fitness_note_edit"}

# The only exempt edit shape: `append_text` strictly ADDS to the end of a note.
# It cannot remove or overwrite anything, so authorizing it can lose nothing.
_NARROW_EDIT_ARGS = ("append_text",)

# Everything else a notes_edit can do requires the user's own authorization.
#
# `remove_text` was briefly exempt here on the grounds that it deletes exactly
# one matched span and refuses on zero/multiple matches. Narrowness is not
# authorization: a precise deletion is still a deletion, and "it can only
# destroy a little" is not a reason to run it unasked. Reverted 2026-09-27 on
# David's instruction. `content` replaces the whole body; `title` renames.
_WHOLE_NOTE_EDIT_ARGS = ("content", "title", "remove_text")


def is_additive_capture_call(tool_name: str, arguments) -> bool:
    """True when this specific call only records, appends, or narrowly revises.

    Capture (a new note) and pure APPEND are exempt, because neither can lose
    anything that already exists and because the disclosure is itself the
    request — "Remember that I met Dana from Acme" carries no imperative verb
    at all, and demanding one refused 7 of 9 realistic phrasings.

    Everything that can remove or overwrite existing text — `content`,
    `title`, `remove_text` — needs the user's own authorization and is NOT
    exempt, however narrowly scoped its arguments are. A correction therefore
    lands as an append (an audit trail, which is the right shape for "actually
    it's X, not Y" anyway), not as an unauthorized deletion.

    `arguments` is the call's own argument dict (whatever the model passed);
    anything unparseable is treated as NOT a capture, so the gate stays the
    default and this can only ever widen authority for a shape it can actually
    verify.
    """
    if tool_name in CAPTURE_TOOLS:
        return True
    if tool_name in APPEND_ONLY_CAPABLE and isinstance(arguments, dict):
        if any(arguments.get(k) for k in _WHOLE_NOTE_EDIT_ARGS):
            return False
        for key in _NARROW_EDIT_ARGS:
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return True
    return False

# Imperative/action verbs David actually uses when he wants Sara to do
# something, as opposed to reporting or reacting to something. Deliberately
# a fixed lexicon, not a second LLM call (Phase 5 non-goal: no unconstrained
# second agent as the primary gate).
ACTION_INTENT_VERBS = (
    "add", "create", "log", "record", "save", "delete", "remove", "cancel",
    "change", "update", "edit", "set", "schedule", "remind", "send", "email",
    "text", "message", "make a", "start", "stop", "end", "finish", "complete",
    "check off", "mark", "move", "file", "put", "book", "reschedule",
    "postpone", "download", "upload", "attach", "grab", "pull", "give me",
    "get me", "share", "please add", "can you add", "can you create",
    "can you log", "can you set", "can you schedule", "can you remind",
    "can you delete", "can you cancel", "can you send", "can you update",
    "can you change", "could you add", "could you create", "could you log",
)

_ACTION_VERB_RE = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in ACTION_INTENT_VERBS) + r")\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# "Don't delete anything" — a prohibition earlier in the same sentence turns
# a listed verb into the opposite of authorization. Checked as a substring
# of the text before the match, so multi-word forms ("do not", "no need
# to") work the same as contractions.
_NEGATION_MARKERS = (
    "don't", "do not", "doesn't", "does not", "didn't", "did not",
    "won't", "will not", "wouldn't", "would not", "shouldn't", "should not",
    "never", "no need to", "not going to", "not gonna", "can't", "cannot",
    "can not",
)

# "My workout is complete" — a copula immediately before the matched verb
# means it's describing a state, not requesting one.
_COPULA_BEFORE_RE = re.compile(r"\b(is|was|are|were|'s|has been|have been|seems|looks|sounds)\s*$")

# Verbs that are just as common as plain nouns ("the email", "a text", "my
# update") as they are as imperatives ("email David", "text me"). A
# determiner or possessive immediately before one of these means it's the
# noun — David reporting on or referring to something, not asking for it.
_NOUN_AMBIGUOUS_VERBS = {"email", "message", "text", "update", "set", "post", "draft"}
_DETERMINER_BEFORE_RE = re.compile(r"\b(the|a|an|my|his|her|our|their|this|that|your|its)\s*$")

# A sentence can carry an unrelated denial and a real request as separate
# clauses ("Don't worry about that email, but can you schedule a meeting") —
# negation must not reach across a clause boundary into a later, independent
# request. Only the text since the nearest boundary is checked for negation.
_CLAUSE_BREAK_RE = re.compile(r"[,;]| but | however | although | yet ")


def _current_clause(before: str) -> str:
    parts = _CLAUSE_BREAK_RE.split(before)
    return parts[-1] if parts else before


# 2026-09-24 fix: "if i leave it another month i'll have to start charging
# it rent" (pure hyperbole about a donation box, no real request at all)
# matched has_action_intent via "start" — none of the existing guards
# above catch a hypothetical/conditional-obligation framing. Reproduced
# live: `gate_mutating_tools` reopened `reminders_create` on the strength
# of this match with no real request behind it, and the model produced a
# genuine duplicate write (verified in `turns.jsonl` — a second
# `reminders_create` call, identical target, immediately after a real,
# already-successful one). See
# SARA_NATURAL_CONVERSATION_EVALUATION_PLAN_2026_09_23.md's FINDINGS.md,
# item 2, case 23/context_fix_only/trial 2/turn 5.
#
# "I'll/we'll/would have to X" reads in ordinary English as a reluctant,
# hypothetical consequence — not a present request — regardless of which
# verb follows. Scoped to this specific "(will/would) have to" modal-
# obligation construction rather than bare future tense ("I'll schedule
# it tomorrow"), which is a more genuine expression of intent and stays
# actionable.
_HYPOTHETICAL_OBLIGATION_RE = re.compile(
    r"\b(i|we)('ll|'d|\s+will|\s+would)\s+have\s+to\s*$", re.IGNORECASE
)

# "He said 'start the car'" / "the note said 'cancel it'" — a verb that
# appears inside a quoted span is reported/quoted speech, not David
# addressing Sara. Scoped to double quotes only (straight and curly) —
# single quotes are too often just apostrophes ("don't", "it's") to use
# safely as a quotation delimiter here.
#
# 2026-09-24 fix: quote parity used to be computed per-SENTENCE (against
# each `_SENTENCE_SPLIT_RE`-split piece), which breaks the moment a quote
# spans a sentence boundary — 'he said "cancel this. also delete that"
# and hung up.' splits into two sentences, and the second one
# ('also delete that" and hung up.') has an EVEN quote count on its own
# (just the one closing mark), so "delete" read as unquoted even though
# it's still inside the same spoken quotation as "cancel". Parity is now
# computed against the FULL normalized message, using each match's
# absolute position, not its position within its own sentence.
_DOUBLE_QUOTE_CHARS = '"“”'


def _inside_quotes(full_text: str, abs_pos: int) -> bool:
    before = full_text[:abs_pos]
    count = sum(before.count(c) for c in _DOUBLE_QUOTE_CHARS)
    return count % 2 == 1


# "I'll start the report tomorrow" describes DAVID's own future action,
# not a request for SARA to do something — has_action_intent gates
# whether a MUTATING TOOL is offered to the model, and a first-person
# future-intent statement with no Sara-directed language (no "can you",
# "please", bare imperative, etc. — those are separate matches/phrases
# and stay unaffected) must not itself grant that. Deliberately broader
# than _HYPOTHETICAL_OBLIGATION_RE above (which only covers the
# "(will/would) have to" reluctant-obligation shape): this covers the
# plain "I'll/I will/I'm going to" self-referential future tense too.
#
# 2026-09-24 correction: the original pattern required the verb to sit
# IMMEDIATELY after "I'll"/"I'm going to" with nothing in between, so an
# ordinary modal adverb broke it — "I'll PROBABLY start the report
# tomorrow" matched has_action_intent (True) when it should not have,
# same failure mode as the un-corrected version. Fixed with an EXPLICIT
# list of common hedge/modal adverbs (not a generic "any word" allowance —
# a first attempt at that over-matched: "we're likely going to cancel the
# trip" started swallowing enough filler words that a hypothetical
# "I'll need you to start..." would also have been wrongly excluded, the
# opposite failure). Narrow and explicit, matching this file's existing
# style elsewhere (e.g. _NEGATION_MARKERS, _CONTINUATION_PHRASES).
_FUTURE_INTENT_MODIFIERS = (
    "probably", "likely", "definitely", "maybe", "possibly", "honestly",
    "actually", "eventually", "soon", "just",
)
_MODIFIER_GROUP = r"(?:(?:" + "|".join(_FUTURE_INTENT_MODIFIERS) + r")\s+){0,2}"
_SELF_FUTURE_INTENT_RE = re.compile(
    r"\b(i|we)(?:'ll|'m|'re|\s+will|\s+am|\s+are)\s+"
    + _MODIFIER_GROUP
    + r"(?:going\s+to\s+" + _MODIFIER_GROUP + r")?$",
    re.IGNORECASE,
)


# R01 review remediation (live-model validation, 2026-09-25, evidence: a
# live conversation against these fixes): "Take bread off the Grocery Run
# note, leave everything else" — a plainly explicit, unambiguous edit
# request — matched NO verb in ACTION_INTENT_VERBS at all, so notes_edit
# was correctly-per-the-code-but-wrongly-in-effect refused, and the model
# (accurately) reported the edit as blocked rather than fabricating
# success — but a legitimate request went unfulfilled. "take"/"off"/"out"
# is a separable phrasal verb ("take X off", "take the trash out") that a
# flat substring list can't express (the object sits BETWEEN the two
# words). Matched as "take" followed by up to 4 words then "off"/"out",
# not as a bare "take" — bare "take" was deliberately rejected to avoid
# false-positiving on "it'll take a while" / "take it easy", which have no
# reliable copula/hypothetical guard the way "is set"/"was scheduled" do.
_TAKE_OFF_OUT_RE = re.compile(r"\btake\b(?:\s+\S+){0,4}\s+(?:off|out)\b", re.IGNORECASE)


def has_action_intent(message: str) -> bool:
    """True when the message carries positive evidence of a requested
    mutation — an imperative or an explicit write-operation verb — and that
    evidence isn't negated, a plain noun reference, a reported/past-state
    description of something already true, a hypothetical/conditional
    obligation ("I'll have to..."), a first-person future-intent statement
    about David's own action ("I'll start..."), or quoted/reported speech.
    """
    if not message:
        return False
    # Normalize curly quotes so "don't"/"don't" match the same way.
    normalized = message.replace("’", "'").replace("‘", "'")
    full_lower = normalized.lower()
    offset = 0
    for sentence in _SENTENCE_SPLIT_RE.split(normalized):
        low = sentence.lower()
        # Find this sentence's absolute start in the full text (searching
        # forward from the end of the previous sentence) so quote parity
        # and other full-text checks can use an absolute position instead
        # of one that resets to 0 at every sentence boundary.
        sentence_start = full_lower.find(low, offset)
        if sentence_start == -1:
            sentence_start = offset
        for m in _ACTION_VERB_RE.finditer(low):
            clause = _current_clause(low[: m.start()])
            if any(neg in clause for neg in _NEGATION_MARKERS):
                continue
            if _COPULA_BEFORE_RE.search(clause):
                continue
            if _HYPOTHETICAL_OBLIGATION_RE.search(clause):
                continue
            if _SELF_FUTURE_INTENT_RE.search(clause):
                continue
            if _inside_quotes(full_lower, sentence_start + m.start()):
                continue
            if m.group(1) in _NOUN_AMBIGUOUS_VERBS and _DETERMINER_BEFORE_RE.search(clause):
                continue
            return True
        for m2 in _TAKE_OFF_OUT_RE.finditer(low):
            clause = _current_clause(low[: m2.start()])
            if any(neg in clause for neg in _NEGATION_MARKERS):
                continue
            if _inside_quotes(full_lower, sentence_start + m2.start()):
                continue
            return True
        offset = sentence_start + len(low)
    return False


# Living-world-context plan: a tool executing once must not become standing
# permission for the rest of the conversation — "a previous unrelated write
# is not blanket authorization." Only a message that itself reads as
# confirming/continuing a just-proposed-or-performed action can ride on a
# recent mutation; a generic later message ("okay what else") cannot, even
# if it happens to arrive right after a write.
#
# Deliberately whole-message or short-prefix matched, not a substring
# search anywhere in the text: a long, unrelated message that happens to
# contain the word "yes" somewhere is a fresh request, not a confirmation.
_CONTINUATION_PHRASES = (
    "yes", "yeah", "yep", "yup", "sure", "do it", "go ahead", "please do",
    "sounds good", "do that", "please", "confirmed", "that's right",
    "go for it", "ok do it", "okay do it", "correct", "please go ahead",
    "do the same", "same for", "do that one too", "and the other one too",
)
_MAX_CONTINUATION_WORDS = 6


def is_continuation_of_pending_action(message: str) -> bool:
    """True when `message` reads as confirming or continuing a specific
    action just proposed or performed — never true for an arbitrary later
    message that happens to name the same tool for something new."""
    if not message:
        return False
    low = message.strip().lower().rstrip(".!")
    if not low:
        return False
    if low in _CONTINUATION_PHRASES:
        return True
    if len(low.split()) <= _MAX_CONTINUATION_WORDS:
        for phrase in _CONTINUATION_PHRASES:
            if low.startswith(phrase):
                return True
    return False


def gate_mutating_tools(
    tools: Sequence[Dict[str, Any]],
    message: str,
    last_turn_mutating_tools: Sequence[str] = (),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Drop mutating tools that lack positive action evidence.

    `last_turn_mutating_tools` is the specific set of mutating tools this
    session actually EXECUTED in the immediately preceding turn — not
    "ever, this conversation." It is deliberately NOT standing
    authorization by itself: a tool listed there survives only when
    `message` also reads as a continuation of that specific action
    (`is_continuation_of_pending_action`). A generic later message that
    happens to still be about the same tool needs its own action evidence
    like any other turn.

    Returns (kept_schemas, dropped_names) — dropped_names is for turn
    diagnostics ("tool selection logs explain why every schema was
    included/excluded").
    """
    action_ok = has_action_intent(message)
    continuation_ok = bool(last_turn_mutating_tools) and is_continuation_of_pending_action(message)
    recent_set = set(last_turn_mutating_tools)

    # The operation contract's own view of what this turn could reasonably ask
    # for. Used as a WIDENING alongside the rules below, never a narrowing:
    # everything the verb lexicon would have kept is still kept, and the
    # contract adds the cases it cannot express — an elliptical follow-up ("And
    # one for the dentist on October 2nd at 9am"), a correction with no update
    # verb ("Make that two gallons, not one"). Both were found live: the
    # boundary would have authorized them and the MENU did not contain the
    # tool, so Sara told David she had no way to do it.
    #
    # Local import: operation_contract imports this module, so a module-level
    # import here would be a cycle.
    try:
        from app.services.operation_contract import (
            operation_kind_for as _kind_for,
            selection_kinds_for_message as _selection_kinds,
        )
        contract_kinds = _selection_kinds(message, last_turn_mutating_tools)
    except Exception:  # never let selection fail closed on an import problem
        _kind_for = None
        contract_kinds = None

    kept: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for schema in tools:
        name = ((schema.get("function") or {}).get("name")) or ""
        if not is_mutating_tool(name):
            kept.append(schema)
            continue
        if name in ALWAYS_ALLOWED_MUTATING or action_ok:
            kept.append(schema)
            continue
        # Capture tools stay on the wire even with no imperative verb — see
        # `is_additive_capture_call`. Selection can only judge by NAME (the
        # model hasn't chosen arguments yet), so `notes_edit` is offered here
        # and it is the execution boundary that checks whether the call it
        # actually made was additive or destructive. Offering a tool is not
        # authorizing it; that two-layer split is the pre-existing contract
        # this follows rather than widens.
        if name in CAPTURE_TOOLS or name in APPEND_ONLY_CAPABLE:
            kept.append(schema)
            continue
        if continuation_ok and name in recent_set:
            kept.append(schema)
            continue
        if contract_kinds is not None and _kind_for is not None:
            try:
                if _kind_for(name, None) in contract_kinds:
                    kept.append(schema)
                    continue
            except Exception:
                pass
        dropped.append(name)

    return kept, dropped


# Harness/thinking/personality plan, Phase 4: "delete the bank reminder"
# when two reminders match must not authorize deleting both. Reproduced
# live in the harness evaluation — thinking-off, given a fixture with two
# candidates for "the bank" reminder, called reminders_cancel on BOTH in
# the same round instead of asking which one. `gate_mutating_tools` above
# decides whether a tool is offered at all, before the model has chosen
# anything — this is a different, narrower boundary: given the model's
# ACTUAL tool_calls for one round, catch the specific shape of "the same
# removal tool, multiple targets, no bulk language," and block execution
# in favor of asking. A model that reaches for a list/search tool first,
# sees two matches, then calls delete twice is exactly the incident this
# exists to stop — without a second model judge, just a structural check
# on the round's own tool_calls.
_REMOVAL_TOKENS = {"delete", "remove", "cancel"}

# Deliberately short and explicit rather than a broad "any plural-sounding
# word" heuristic — false positives here (treating an ambiguous request as
# bulk-authorized) are the expensive direction of error.
_BULK_INTENT_RE = re.compile(
    r"\b(all(?:\s+of\s+(?:them|these|those))?|both|every(?:\s+one)?|each\s+one|"
    r"the\s+whole\s+(?:list|thing|set)|entire\s+list|everything)\b",
    re.IGNORECASE,
)

# Post-hoc correction (harness/thinking/personality plan, Milestone-A
# review, 2026-09-22): `has_bulk_intent` used to be a bare
# `_BULK_INTENT_RE.search(message)` over the WHOLE message — so "Delete
# the bank reminder, not both." (bulk word negated) and "Delete the bank
# reminder after checking all my calendars." (bulk word in an unrelated
# clause) both incorrectly read as bulk-authorized. A removal verb three
# clauses away from an unrelated "all" must not authorize anything, and a
# bulk word immediately negated must not either. Fixed by scoping the bulk
# check to the CLAUSE that actually contains a removal verb, and refusing
# a match whose nearest few words include a negation.
_REMOVAL_VERB_RE = re.compile(r"\b(delete|remove|cancel)\b", re.IGNORECASE)
# Splits on sentence punctuation, or a comma/bare boundary before a
# conjunction that commonly introduces an unrelated clause — "after
# checking all my calendars" must not share a clause with "delete the
# bank reminder" just because there is no period between them.
_CLAUSE_SPLIT_RE = re.compile(
    r"[.;!?]+|,?\s*\b(?:and|but|after|before|then|except|while|once)\b",
    re.IGNORECASE,
)
# "n't" has no leading \b of its own — it is always the tail of a
# contraction ("don't", "won't"), so the character immediately before it
# is a letter, and \b never fires between two word characters. Matched as
# a bare suffix (`n't\b`) instead of `\bn't\b`, which can never match
# inside a real contraction at all.
_NEGATION_RE = re.compile(r"\b(not|never|without|except)\b|n't\b", re.IGNORECASE)
# How close a negation has to be, in characters, to the start of the bulk
# match to count — "not both" and "don't delete all of them" both qualify;
# a negation from an entirely different clause should already have been
# excluded by the clause split above, so this window only needs to cover
# "not X, Y, Z both" style hedges within one clause.
_NEGATION_WINDOW_CHARS = 24


def is_removal_tool(name: str) -> bool:
    """A tool whose ambiguous same-turn repetition is worth flagging —
    narrower than `is_mutating_tool`: an update/create called twice with
    different arguments is normal (two different notes, two different
    reminders being ADDED); a delete/cancel called twice with different
    target IDs is the specific "acted on every candidate instead of
    asking" shape."""
    return bool(_tokens(name) & _REMOVAL_TOKENS)


def has_bulk_intent(message: str) -> bool:
    """True when the user's own words, IN THE SAME CLAUSE AS A REMOVAL
    VERB and not negated there, authorize acting on more than one match —
    "delete both", "cancel all of them" — as opposed to a bare singular
    reference ("delete the bank reminder") that merely happens to match
    multiple candidates, a bulk word negated ("not both"), or a bulk word
    that belongs to an unrelated clause ("...after checking all my
    calendars").
    """
    if not message:
        return False
    for clause in _CLAUSE_SPLIT_RE.split(message):
        if not _REMOVAL_VERB_RE.search(clause):
            continue
        for m in _BULK_INTENT_RE.finditer(clause):
            window = clause[max(0, m.start() - _NEGATION_WINDOW_CHARS):m.start()]
            if _NEGATION_RE.search(window):
                continue
            return True
    return False


def find_ambiguous_same_turn_removals(
    tool_calls: Sequence[Dict[str, Any]], message: str,
    prior_attempts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Tool-call ids to BLOCK: calls to the same removal-shaped tool, with
    DIFFERENT arguments (different targets), when the user's message shows
    no bulk intent for that removal.

    `prior_attempts` (optional) is `{tool_name: set(of argument JSON
    strings already attempted THIS TURN, any earlier round}` — post-hoc
    correction: the original version of this function only ever looked at
    ONE round's tool_calls, so a model (or an adversarial actor) that
    called delete on candidate A in round 1 and candidate B in round 2
    sailed through both times, since neither round alone looked
    "multiple." Passing the running per-turn history closes that: a second
    DISTINCT target for the same removal tool is blocked whether it shows
    up in the same round or three rounds later. The caller (main_simple.py)
    owns updating this dict after each round — see `_chat_with_tools_inner`.

    Returns an empty list when nothing looks ambiguous (including: bulk
    intent present, so any count is authorized; or the repeated calls have
    IDENTICAL arguments, which is `_repeat_tool_note`'s territory, not
    this — a true duplicate is not "acted on every candidate," it's the
    same target asked about twice).

    Known, stated limitation: a removal tool's very FIRST call for a given
    turn, when it is the only one seen so far (this round and every prior
    round), cannot be distinguished from a legitimately unambiguous
    single-target request by this check alone — it has no visibility into
    whether an earlier READ tool's result actually returned multiple
    candidates. It executes normally. The SECOND distinct target for that
    same tool this turn is what gets caught. This is a real, narrower
    guarantee than "zero speculative writes ever" and is documented as
    such rather than silently assumed away.
    """
    if has_bulk_intent(message):
        return []

    from app.tools.mutating import tool_call_name  # local import: avoid a module cycle

    prior_attempts = prior_attempts or {}
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for tc in tool_calls or []:
        name = tool_call_name(tc)
        if name and is_removal_tool(name):
            by_name.setdefault(name, []).append(tc)

    blocked: List[str] = []
    for name, calls in by_name.items():
        this_round_args = {call.get("function", {}).get("arguments", "") for call in calls}
        seen_before = set(prior_attempts.get(name) or ())
        all_targets_this_turn = this_round_args | seen_before
        if len(all_targets_this_turn) < 2:
            continue  # only one distinct target attempted so far, this round or any prior one
        blocked.extend(call.get("id", "") for call in calls)
    return blocked


def record_removal_attempts(
    prior_attempts: Dict[str, Any], tool_calls: Sequence[Dict[str, Any]],
) -> None:
    """Mutates `prior_attempts` in place, adding every removal-tool call in
    `tool_calls` (whether it went on to execute or was blocked) to the
    running per-turn history `find_ambiguous_same_turn_removals` checks
    future rounds against. Call once per round, after deciding what to
    block for that round — including calls that WERE blocked, since a
    blocked attempt still counts as "the model tried this target" for the
    purpose of recognizing a THIRD distinct target later as still
    ambiguous.
    """
    from app.tools.mutating import tool_call_name

    for tc in tool_calls or []:
        name = tool_call_name(tc)
        if not name or not is_removal_tool(name):
            continue
        args = tc.get("function", {}).get("arguments", "")
        prior_attempts.setdefault(name, set()).add(args)


# ── R01 review remediation (2026-09-25): recurring-scope authorization ──
#
# Original plan item 6: "Require explicit recurring scope before activating
# a standing order. Hypothetical or one-time language cannot become
# recurring authority." The execution-boundary fix (main_simple.py
# execute_tool) closed the pure BYPASS (a mutating tool reaching execution
# with NO action evidence at all, per J11), but a message with real,
# unambiguous one-time action intent — "turn on the porch light" — still
# satisfies `has_action_intent` and would authorize `standing_order_create`
# even though the user never asked for anything recurring. A standing
# order is categorically different from every other mutating tool: it
# doesn't just act once, it installs standing authority to act again,
# unsupervised, on every future occurrence. That requires its own,
# additional evidence — not just "some action verb was present somewhere."
RECURRING_ESTABLISHING_TOOLS = {"standing_order_create"}

_RECURRING_SCOPE_MARKERS = (
    "every time", "each time", "every day", "every morning", "every night",
    "every week", "every arrival", "every time i", "whenever i", "whenever",
    "always", "from now on", "automatically", "standing order", "recurring",
    "each morning", "each night", "each week", "any time i", "anytime i",
    "each arrival", "going forward",
)


def has_recurring_scope(message: str) -> bool:
    """True when the message itself asks for a RECURRING/standing action,
    not just a one-time one. "Turn on the porch light" (real, one-time
    action intent) is not enough on its own to authorize
    `standing_order_create`; "turn on the porch light every time I get
    home" or "set up a standing order for..." is."""
    if not message:
        return False
    low = message.lower()
    return any(marker in low for marker in _RECURRING_SCOPE_MARKERS)


# ── R01 review remediation round 2 (2026-09-26): operation-and-target
# scoping, replacing the round-1 clause-counting approach entirely ──────
#
# J10 (evidence J10_trial1_TURN3_WRONG_ENTITY_CANCELLED_CROSS_CONTEXT /
# J10_trial2_TURN3_SECOND_WRONG_ENTITY_ACTION): "The Cedar follow-up is
# handled. Close that thread and stop reminding me about it." correctly
# resolved the real thread (`resolve_thread`) AND additionally cancelled
# an unrelated, real research plan (`cancel_research_plan`, trial 1) or
# reminder (`reminders_cancel`, trial 2) — a SEPARATE tool, on a SEPARATE
# entity, that the message gave no independent evidence for.
#
# Round 1's fix counted how many action-evidenced CLAUSES the message had
# and allowed that many scope-sensitive calls BY ORDER — which is not
# target scoping at all: a wrong-target call that happened to be first (or
# the ONLY call) sailed through untouched, because "1 clause, 1 call"
# looked fine regardless of WHICH call it was. Review correction: replace
# call-order/clause-count with genuine per-call target scoping. Every
# scope-sensitive call, including the first and only one, must be
# supported by the message actually referencing that tool's DOMAIN — not
# merely "some action was requested somewhere."
#
# `tool_domain_evidenced(name, message)` is the core primitive: does the
# message contain a NOUN naming the kind of thing `name` acts on? Built on
# NOUN forms specifically, not verb forms — "stop reminding me about it"
# does NOT satisfy the reminder domain (no occurrence of "reminder" as a
# word; "remind"/"reminding" don't match), which is exactly why it must
# not have authorized a reminders_cancel call in trial 2: the phrase
# describes an ACTION on the thread ("stop nagging me about THIS"), not a
# reference to a separate reminder ENTITY. "that thread" DOES satisfy the
# thread domain ("thread" is a literal noun match). This is deliberately
# conservative in the noun-only direction: "stop reminding me about the
# dentist appointment" (no literal "reminder") would also fail to
# authorize a genuine reminders_cancel — a real, accepted false-refusal
# risk, the safe-direction trade-off this whole task has made throughout
# (an occasional unnecessary refusal is far cheaper than an unrelated
# destructive action).
#
# Because this check is PURELY a function of (tool_name, message) — no
# call-history, no ordering, no "already counted" bookkeeping — it is
# retry-proof by construction: a call blocked once for lacking domain
# evidence is blocked identically on every subsequent attempt this turn,
# because the message providing (or not providing) that evidence never
# changes within a turn. Round 1's `find_cross_tool_unscoped_mutations`
# had a real retry-bypass bug here: `record_cross_tool_attempts` recorded
# BOTH allowed and blocked calls into the same `seen_signatures` set, and
# the "exact repeat is not a new ask" carve-out then silently un-blocked a
# retried WRONG call the second time it was attempted with identical
# arguments, since it now matched something "already seen." This redesign
# has no such state to exploit — there is nothing to carry across rounds.
_SCOPE_SENSITIVE_TOKENS = {
    "cancel", "delete", "remove", "resolve", "complete", "abandon",
    "close", "archive", "deactivate",
}


def is_scope_sensitive_tool(name: str) -> bool:
    """A tool whose effect TERMINATES/CLOSES/REMOVES an existing entity —
    the class of action `find_target_unscoped_mutations` checks is
    actually supported by the message's own reference to that entity's
    domain. Deliberately a separate, broader set from `is_removal_tool`
    (which stays scoped to its own existing same-tool-multiple-targets
    check) — this one also covers "resolve"/"complete"/"abandon"/
    "archive"/"deactivate", the verbs the J10 confirmed failure actually
    used."""
    return bool(_tokens(name) & _SCOPE_SENSITIVE_TOKENS)


# Hand-curated noun patterns for domains this codebase's real registered
# tools actually act on (verified against app/tools/*.py — resolve_thread,
# cancel_research_plan, reminders_cancel, notes_delete, list_remove,
# timers_cancel, standing_order_* — see tests for the full list checked).
# Deliberately NOUN-only, no bare verb stems, and deliberately avoids
# single common words that would over-match ("plan" alone, "set" alone).
_CURATED_DOMAIN_PATTERNS: Dict[str, str] = {
    "thread": r"\b(threads?|follow[- ]?ups?)\b",
    "research_plan": r"\bresearch\b|\binvestigations?\b",
    "reminders": r"\breminders?\b",
    "notes": r"\bnotes?\b",
    "list": r"\blists?\b",
    "timers": r"\btimers?\b",
    "standing_order": r"\bstanding\s+orders?\b|\bautomat(?:ion|ic)\b|\brecurring\b",
}


def _tool_domain_stem(name: str) -> str:
    """Derive a domain identifier from a tool name by stripping the
    scope-sensitive verb token(s), wherever they occur — prefix or suffix
    — leaving the entity-naming remainder. "resolve_thread" -> "thread";
    "cancel_research_plan" -> "research_plan"; "reminders_cancel" ->
    "reminders"; "map_delete_node" -> "map_node"."""
    filtered = [t for t in name.lower().split("_") if t and t not in _SCOPE_SENSITIVE_TOKENS]
    return "_".join(filtered) or name.lower()


def _generic_domain_pattern(stem: str) -> "re.Pattern":
    """Fallback for any scope-sensitive tool outside the curated set above
    — matches any individual word (>=3 chars) from the domain stem, each
    with an optional trailing 's' for plurals. Looser than the curated
    patterns (a real trade-off for tools this session didn't specifically
    verify against evidence), but still genuine target scoping — a
    complete stranger to the message is still refused — rather than the
    "any tool at all, as long as count/order looked right" gap this
    replaces."""
    words = [w for w in stem.split("_") if len(w) >= 3]
    if not words:
        words = [stem] if stem else ["x"]
    alts = []
    for w in words:
        w_re = re.escape(w)
        alts.append(w_re if w.endswith("s") else w_re + "s?")
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b", re.IGNORECASE)


_domain_pattern_cache: Dict[str, "re.Pattern"] = {}


def _domain_pattern_for_tool(name: str) -> "re.Pattern":
    stem = _tool_domain_stem(name)
    if stem in _domain_pattern_cache:
        return _domain_pattern_cache[stem]
    pattern_str = _CURATED_DOMAIN_PATTERNS.get(stem)
    pattern = re.compile(pattern_str, re.IGNORECASE) if pattern_str else _generic_domain_pattern(stem)
    _domain_pattern_cache[stem] = pattern
    return pattern


def tool_domain_evidenced(tool_name: str, message: str) -> bool:
    """True when `message` contains a noun naming the kind of entity
    `tool_name` acts on. This is the actual target-scoping primitive —
    genuine per-call authorization, not a count or an order position."""
    if not message:
        return False
    return bool(_domain_pattern_for_tool(tool_name).search(message))


def find_target_unscoped_mutations(
    tool_calls: Sequence[Dict[str, Any]], message: str,
) -> List[str]:
    """Tool-call ids to BLOCK: scope-sensitive calls whose DOMAIN is not
    referenced anywhere in the message — independent of call order, call
    count, or whether this is the first, only, or a repeated attempt (see
    module comment above for the full J10 + retry-bypass rationale this
    replaces).

    Deliberately stateless — no `prior_calls`/history parameter, because
    none is needed: the same message produces the same verdict for the
    same tool every time it's checked, this round or three rounds later,
    closing the retry-bypass class of bug by construction rather than by
    tracking attempts.

    Genuinely different, explicit requests remain authorized: each tool's
    domain is checked independently, so "cancel the standing order and
    mark the reminder done" authorizes BOTH (each domain noun present) —
    this function never limits COUNT within an already-evidenced domain,
    only PRESENCE of the domain at all. (Multiple targets of the SAME tool
    remain the existing `find_ambiguous_same_turn_removals`'s job,
    unchanged.) `has_bulk_intent` is intentionally NOT a blanket override
    here (round 1's version treated any bulk phrase anywhere as
    authorizing every scope-sensitive call in the turn, regardless of
    domain — the review's "bulk wording with targets outside the
    requested scope" finding): "cancel all my reminders about groceries"
    authorizes reminder-domain calls (bulk phrasing already lets
    `find_ambiguous_same_turn_removals` allow more than one reminder
    target), but does nothing for an unrelated standing_order call, which
    still needs its own domain evidence.
    """
    from app.tools.mutating import tool_call_name

    blocked: List[str] = []
    for tc in tool_calls or []:
        name = tool_call_name(tc)
        if not name or not is_scope_sensitive_tool(name):
            continue
        if not tool_domain_evidenced(name, message):
            blocked.append(tc.get("id", ""))
    return blocked
