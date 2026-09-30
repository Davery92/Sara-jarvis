"""Deterministic dialogue-state capsule (chat harness repair Phase 4).

The 2026-09-16 morning conversation: Sara asked the same shoulder question
four times (including after David answered it), reasserted a superseded set
count after David corrected it, and described a completed workout as an
active between-set period. None of this needs another LLM call to fix — the
conversation transcript already contains the answer. This module builds a
compact, conservative summary of "what's already settled" from the raw
turns (roles + text only, no domain events) so it can be handed to the model
as a small, high-priority context block that supersedes stale assumptions.

Deliberately NOT an LLM call (Phase 4 non-goal: no second unconstrained
agent as the primary repetition detector). Extraction is conservative by
design: when in doubt, treat a question as answered / a fact as not
superseded, rather than risk false positives that make Sara look confused
about her own certainty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "has", "have", "had", "you", "your", "yours",
    "i", "me", "my", "we", "us", "our", "it", "its", "this", "that",
    "and", "or", "but", "to", "of", "in", "on", "at", "for", "with",
    "how", "what", "when", "where", "why", "still", "any", "now",
}


def _stem(word: str) -> str:
    """Bare-bones plural stemming — "shoulders" -> "shoulder" — so overlap
    checks aren't defeated by singular/plural mismatches. Discovered against
    the real 2026-09-16 transcript: "How's the shoulder feeling...?" vs.
    "Shoulders all good..." shared no words without this and the question
    stayed marked unanswered despite plainly being answered."""
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _content_words(text: str) -> set:
    return {
        _stem(w) for w in _WORD_RE.findall((text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


def extract_questions(text: str) -> List[str]:
    """Trailing-'?' sentences in a block of text, in order."""
    if not text or "?" not in text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip().endswith("?")]


def _is_answered(question: str, later_user_messages: Sequence[str]) -> bool:
    """Conservative: any later user message that shares a content word with
    the question, or is short enough to plausibly be a direct reply to it."""
    q_words = _content_words(question)
    for msg in later_user_messages:
        if q_words and (q_words & _content_words(msg)):
            return True
        if 0 < len(msg.split()) <= 6:
            return True
    return False


@dataclass
class Correction:
    supersession_key: str
    value: str
    old_value: str
    raw_text: str
    authority: str = "user_explicit"


@dataclass
class DialogueState:
    latest_user_message: str = ""
    unanswered_questions: List[str] = field(default_factory=list)
    corrections: List[Correction] = field(default_factory=list)
    activity_signal: Optional[str] = None  # "completed" | None


def _last_n_indices_by_role(messages: Sequence[Dict[str, str]], role: str, n: int) -> List[int]:
    idxs = [i for i, m in enumerate(messages) if (m.get("role") or "") == role]
    return idxs[-n:]


def _unanswered_questions(messages: Sequence[Dict[str, str]]) -> List[str]:
    out: List[str] = []
    for idx in _last_n_indices_by_role(messages, "assistant", 2):
        content = messages[idx].get("content") or ""
        if not isinstance(content, str):
            continue
        later_user = [
            m.get("content") or "" for m in messages[idx + 1:]
            if (m.get("role") or "") == "user" and isinstance(m.get("content"), str)
        ]
        for q in extract_questions(content):
            if not _is_answered(q, later_user):
                out.append(q)
    return out


# "4 sets of 135x6", "3 reps of 10" — captures (count, unit, identifier).
# The identifier ("135x6", "10") is the supersession key: it's the part of
# the claim that names WHAT is being counted, stable across a correction to
# HOW MANY of it there were.
_COUNT_OF_RE = re.compile(
    r"\b(\d+)\s*(sets?|reps?|rounds?|times?)\s+of\s+([a-z0-9]+(?:x[a-z0-9]+)?)\b",
    re.IGNORECASE,
)


def _numeric_claims(text: str) -> List[tuple]:
    """[(count, unit, identifier)] for every "N unit of X" claim in text."""
    if not text or not isinstance(text, str):
        return []
    return [(m.group(1), m.group(2).lower(), m.group(3).lower()) for m in _COUNT_OF_RE.finditer(text)]


def _detect_corrections(messages: Sequence[Dict[str, str]]) -> List[Correction]:
    """A later message (from either speaker) restating "N unit of X" with a
    DIFFERENT N than an earlier claim about the same X is a correction — the
    later, user-stated count wins. Only user-originated corrections are
    surfaced: a user restating a count Sara got wrong is a correction: Sara
    restating her own earlier number is not evidence of anything."""
    seen: Dict[str, tuple] = {}  # identifier -> (count, unit, raw_text, is_user)
    corrections: List[Correction] = []

    for m in messages:
        content = m.get("content")
        if not isinstance(content, str):
            continue
        is_user = (m.get("role") or "") == "user"
        for count, unit, identifier in _numeric_claims(content):
            prior = seen.get(identifier)
            if prior is not None and prior[0] != count and is_user:
                corrections.append(Correction(
                    supersession_key=f"count_of:{identifier}",
                    value=f"{count} {unit} of {identifier}",
                    old_value=f"{prior[0]} {prior[1]} of {identifier}",
                    raw_text=content.strip(),
                ))
            seen[identifier] = (count, unit, content, is_user)

    return corrections


# Deliberately conservative and domain-agnostic: only phrases that are
# unambiguous evidence an activity just ended trigger the "completed" signal.
# Absence of a match means "no signal", not "still active" — this module
# never asserts an activity is ongoing, only that it's confirmed over.
#
# "walking to"/"heading to"/"on my way to" and "pain is gone"/"pain has gone
# away" used to be in this set and were themselves the 2026-09-16 bug: none
# of them is completion evidence. Heading somewhere is (if anything) a
# workout STARTING, not ending, and a symptom going away is an observation
# about David's body, not a claim about whether a workout is over.
_COMPLETION_PHRASES = (
    "workout was good", "workout was great", "workout complete",
    "finished the workout", "done with the workout", "just finished",
    "that's done", "wrapped up", "all done",
)

# A later message carrying one of these supersedes any earlier completion
# signal — starting or resuming an activity resets "over" back to unknown.
# This is what makes "finished morning workout" ... "started evening
# workout, between sets" resolve correctly: the scan below stops at the
# first (i.e. most recent) signal of EITHER kind, so a later restart wins
# over an earlier completion instead of the completion always winning.
_RESTART_PHRASES = (
    "starting my workout", "starting the workout", "started my workout",
    "started the workout", "beginning my workout", "back at the gym",
    "between sets", "mid-set", "mid-workout", "warming up", "warmup",
    "about to start", "heading to the gym", "heading back to the gym",
)


def _detect_activity_signal(messages: Sequence[Dict[str, str]]) -> Optional[str]:
    for m in reversed(messages):
        if (m.get("role") or "") != "user":
            continue
        content = m.get("content")
        if not isinstance(content, str):
            continue
        low = content.lower()
        if any(p in low for p in _RESTART_PHRASES):
            return None
        if any(p in low for p in _COMPLETION_PHRASES):
            return "completed"
    return None


def build_dialogue_state(messages: Sequence[Dict[str, str]]) -> DialogueState:
    """messages: [{"role": "user"|"assistant", "content": str}, ...], oldest first."""
    latest_user = ""
    for m in reversed(messages):
        if (m.get("role") or "") == "user" and isinstance(m.get("content"), str):
            latest_user = m["content"]
            break

    return DialogueState(
        latest_user_message=latest_user,
        unanswered_questions=_unanswered_questions(messages),
        corrections=_detect_corrections(messages),
        activity_signal=_detect_activity_signal(messages),
    )


def render_dialogue_state_block(state: DialogueState) -> str:
    """Compact prompt block. Empty string when there's nothing worth saying —
    an empty "conversation state" section is worse than no section."""
    lines: List[str] = []

    if state.corrections:
        lines.append("Corrections David has made this conversation (these override anything said earlier, by either of you):")
        for c in state.corrections:
            lines.append(f"- {c.value} (was: {c.old_value}) — treat {c.old_value} as no longer true")

    if state.activity_signal == "completed":
        lines.append("David has confirmed the activity/workout just ended. Do not describe it as in progress, between sets, or ongoing.")

    if state.unanswered_questions:
        lines.append("Questions you already asked that David has not answered yet — do not ask these again unless he raises the topic himself:")
        for q in state.unanswered_questions[-3:]:
            lines.append(f"- {q}")

    if not lines:
        return ""
    return "## Conversation state (this turn)\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Post-hoc repair (only usable on non-streaming/full-text response paths —
# once tokens are on the wire in a streamed reply, repair can't undo them).
# ---------------------------------------------------------------------------

def _near_duplicate_question(a: str, b: str, min_overlap: float = 0.6) -> bool:
    a_words, b_words = _content_words(a), _content_words(b)
    if not a_words or not b_words:
        return False
    overlap = len(a_words & b_words) / max(1, min(len(a_words), len(b_words)))
    return overlap >= min_overlap


def is_duplicate_or_answered_trailing_question(
    candidate_response: str,
    recent_assistant_messages: Sequence[str],
    dialogue_state: DialogueState,
) -> bool:
    """True when candidate_response's trailing question is a near-duplicate
    of a question from the last two assistant replies — and, when that prior
    question isn't still in `dialogue_state.unanswered_questions`, David has
    since answered it, making the re-ask doubly wrong."""
    questions = extract_questions(candidate_response)
    if not questions:
        return False
    trailing = questions[-1]

    unanswered_now = set(dialogue_state.unanswered_questions)
    for prior_text in recent_assistant_messages[-2:]:
        for prior_q in extract_questions(prior_text or ""):
            if _near_duplicate_question(trailing, prior_q):
                return True
            if prior_q not in unanswered_now and _near_duplicate_question(trailing, prior_q, min_overlap=0.4):
                return True  # a looser match, but the original was answered — re-asking it is worse

    return False


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def find_repeated_sentences(
    candidate_response: str, recent_assistant_messages: Sequence[str], min_overlap: float = 0.75,
) -> List[str]:
    """Declarative sentences in candidate_response that near-duplicate one
    already said in the last two assistant replies — the general form of
    "repeated the same RingCentral timing in several replies": a plain fact
    restated verbatim across turns, not a question (those are handled by
    `is_duplicate_or_answered_trailing_question`).

    Detection only. Unlike the trailing-question case there's no safe
    generic textual repair — removing an arbitrary mid-paragraph sentence
    risks garbled output — so this is for logging/diagnostics
    ("detect resurfacing" per the plan) rather than an automatic edit.
    """
    prior_sentences = [
        s for prior in recent_assistant_messages[-2:] for s in _sentences(prior or "")
        if not s.endswith("?")
    ]
    if not prior_sentences:
        return []

    repeated = []
    for s in _sentences(candidate_response):
        if s.endswith("?") or len(_content_words(s)) < 3:
            continue  # questions handled separately; too-short sentences are noise
        for prior_s in prior_sentences:
            a_words, b_words = _content_words(s), _content_words(prior_s)
            if not a_words or not b_words:
                continue
            overlap = len(a_words & b_words) / max(1, min(len(a_words), len(b_words)))
            if overlap >= min_overlap:
                repeated.append(s)
                break
    return repeated


def strip_duplicate_trailing_question(candidate_response: str) -> str:
    """Deterministic repair: drop a duplicated trailing question when the
    remaining text is a complete answer on its own. One repair attempt only
    — this is not a loop, just a single textual edit."""
    questions = extract_questions(candidate_response)
    if not questions:
        return candidate_response
    trailing = questions[-1]
    idx = candidate_response.rfind(trailing)
    if idx == -1:
        return candidate_response
    remainder = candidate_response[:idx].rstrip()
    if not remainder:
        # The whole response was the question — nothing safe to fall back to.
        return candidate_response
    return remainder
