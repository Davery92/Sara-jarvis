"""Candidate replacement for `app.services.context_router.
classify_conversation_mode`, written for isolated testing only (2026-09-24
follow-up review, item 3). NEVER imported by production code; NEVER
deployed by this study. Compared against the real function via
`regression_cases.py`, never substituted for it silently.

Two structural changes, not a broader keyword list:

1. **Vulnerable-signal check now runs BEFORE the question check**, and a
   bare trailing question no longer promotes a vulnerable turn to
   `action`/`factual_advice`. Only a question that itself reads as an
   information REQUEST (reusing a narrow request-phrase set, not "any
   question mark") can still do that. Original bug: `action = has_question
   or has_action_verb` meant "what are you up to today?" appended to "my
   dad's got some tests tomorrow" flipped the whole turn to full-context
   mode -- the trailing pleasantry, not the disclosure, decided the mode.

2. **The action-signal check is verb-form and clause aware, reusing
   `app.services.tool_mutation.has_action_intent`'s technique (word-
   boundary verb matching + copula-before exclusion) instead of a bare
   substring scan.** The reviewer is right that widening a keyword list
   (`schedule(d|s)?\\s+a\\b`) does not fix this: that pattern still matches
   "scheduled a full review meeting" verbatim. The actual distinguishing
   signal is not the word form, it's WHO the sentence's subject is —
   "my brain scheduled a meeting" has a figurative/reflexive subject
   ("my brain/head/mind"), never Sara, and is never in the imperative;
   "can you schedule a meeting" / "schedule a meeting" / "I need you to
   schedule a meeting" address Sara directly or use the bare imperative.
   `has_action_intent` cannot tell these apart on its own either (it
   wasn't built to) -- so this module adds one further, narrow check
   specific to that failure: a small denylist of reflexive/figurative
   subjects that, when they immediately precede a matched action verb,
   veto the match. This is a structural exclusion (subject identification),
   not a broader trigger list -- it makes the SAME verbs match in FEWER
   sentences, the opposite direction of the "broader matching" the
   reviewer warned against.
"""
from __future__ import annotations

import re
from typing import Optional

from app.services.context_router import (
    _GREETING_OR_SMALLTALK_RE, _VULNERABLE_SIGNALS, _VULNERABLE_WORD_RE,
)

# Widened vulnerable-signal coverage (review item 3's "genuine scheduling
# requests, including ones embedded in emotional disclosures" and "vulnerable
# disclosure followed by casual questions" categories both need this: the
# original list has no health-appointment language at all, so "tests
# tomorrow" was never recognized as vulnerable in the first place,
# independent of the question-override bug).
_VULNERABLE_SIGNALS_CANDIDATE = _VULNERABLE_SIGNALS + [
    "tests tomorrow", "test tomorrow", "test results", "the results",
    "waiting on results", "appointment tomorrow", "scan tomorrow",
    "checkup tomorrow", "biopsy", "diagnosis",
]

# A question is only itself request-shaped if it asks for information about
# David's own world/data -- not any bare "?". Reuses the spirit of
# context_router._ACTION_SIGNALS' existing read-request phrases, narrowed to
# ones that are actually questions.
_INFO_REQUEST_QUESTION_RE = re.compile(
    r"\b(what'?s my|what is my|what do i have|what'?s on my|do i have|"
    r"have i got|check my|check the|look up|find out|what happened|"
    r"catch me up|can you check|could you check|will you check)\b",
    re.IGNORECASE,
)

# Reflexive/figurative subjects that, immediately before a matched action
# verb, mean the sentence is describing an internal/mental state rather
# than addressing Sara with a request. Deliberately short and explicit
# (same discipline the source file already applies elsewhere in this
# module) -- a false negative here (missing a real figurative case) costs a
# slightly-too-eager suppression-override, not a dropped real request; a
# false positive (vetoing a real request) is the more expensive direction,
# which is why the list stays narrow.
_FIGURATIVE_SUBJECT_RE = re.compile(
    r"\b(my|his|her|their|our)\s+(brain|head|mind|thoughts?)\s+\w*\s*$",
    re.IGNORECASE,
)

# Reuses tool_mutation's word-boundary + copula-aware verb detection
# technique for the specific short verbs that were bare substrings in the
# original _ACTION_SIGNALS list ("schedule" was the reproduced bug; "set",
# "log", "check" share the same shape and are included defensively).
_VERB_FORM_ACTION_RE = re.compile(
    r"\b(schedule|reschedule|remind|set|log|check|cancel|book)\b", re.IGNORECASE
)
_COPULA_OR_PAST_CONTEXT_RE = re.compile(
    r"\b(is|was|are|were|'s|has been|have been|seems|looks|sounds)\s*$"
)

# The remaining, non-verb-form action signals from the original list --
# multi-word request phrases that were never the source of the false
# positive and don't need the verb-form treatment.
_PHRASE_ACTION_SIGNALS = [
    "can you", "could you", "would you", "will you", "please ",
    "remind me", "start a", "add this", "add a", "create a", "note that",
    "send ", "email ", "reply to", "draft", "book ", "order ",
    "turn on", "turn off", "lock the", "unlock the",
    "what's my", "what is my", "what do i have", "what's on my",
    "what happened", "catch me up",
]


def _has_verb_form_action(text_lower: str) -> bool:
    for m in _VERB_FORM_ACTION_RE.finditer(text_lower):
        before = text_lower[: m.start()]
        if _FIGURATIVE_SUBJECT_RE.search(before):
            continue  # "my brain scheduled..." -- figurative subject, veto
        if _COPULA_OR_PAST_CONTEXT_RE.search(before):
            continue  # "the meeting is scheduled" -- reported state, not a request
        return True
    return False


def classify_conversation_mode_candidate(
    message: str,
    intent: Optional[str] = None,
    has_question: Optional[bool] = None,
) -> str:
    text = (message or "").strip()
    if not text:
        return "social"
    text = text.replace("’", "'").replace("‘", "'").replace("ʼ", "'")
    lowered = text.lower()

    # CHANGE 1: vulnerable check runs first and is checked independent of
    # the question flag below.
    vulnerable = (
        any(kw in lowered for kw in _VULNERABLE_SIGNALS_CANDIDATE)
        or bool(_VULNERABLE_WORD_RE.search(lowered))
    )

    # CHANGE 2: action evidence is verb-form-aware (schedule/remind/set/...)
    # plus the remaining literal request phrases -- never a bare "schedule"
    # substring scan.
    has_action_verb = _has_verb_form_action(lowered) or any(
        p in lowered for p in _PHRASE_ACTION_SIGNALS
    )

    # A question only counts as action-evidence if it's itself an
    # information REQUEST about David's world -- not any bare "?".
    is_info_question = bool(_INFO_REQUEST_QUESTION_RE.search(lowered))
    if has_question is None:
        has_question = "?" in text
    action = has_action_verb or is_info_question

    if vulnerable and action:
        return "mixed"
    if vulnerable:
        return "personal_vulnerable"
    if action:
        return "action" if has_action_verb else "factual_advice"

    if len(lowered) < 40 or _GREETING_OR_SMALLTALK_RE.match(text):
        return "social"
    return "social"
