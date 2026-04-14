"""
ACS Session Watchdog — rule-based loop / drift detector.

Runs after every Sara turn. If any rule trips, returns a trigger reason
which the session manager uses to call into the auditor.

Kept deliberately simple and rule-based — the LLM-driven judgment lives in
the auditor itself. This module just answers the cheap question:
"Does this look like a stuck pattern?"
"""

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Tunables — keep conservative initially. We can tighten after watching real triggers.
MIN_TURNS_BEFORE_WATCHDOG = 4              # don't audit in the first few turns
TOPIC_OVERLAP_WINDOW = 3                   # last N assistant turns
TOPIC_OVERLAP_THRESHOLD = 0.55             # Jaccard similarity over keyword sets
DEPENDENCY_REPEAT_WINDOW = 4               # last N turns
DEPENDENCY_REPEAT_THRESHOLD = 3            # same external thing N+ times
TOOL_REPEAT_WINDOW = 6                     # last N assistant turns
TOOL_REPEAT_THRESHOLD = 5                  # same tool N+ times in window
BLOCKED_LANGUAGE_WINDOW = 3                # last N assistant turns

# Phrases that strongly indicate Sara thinks she's blocked but hasn't escalated
_BLOCKED_PHRASES = (
    "i am still blocked",
    "i'm still blocked",
    "still blocked",
    "awaiting david",
    "awaiting david's",
    "waiting for david",
    "i cannot proceed",
    "i can't proceed",
    "endpoint is unresponsive",
    "endpoint is down",
    "infrastructure blockage",
    "blocked by the unresponsive",
    "holding pattern",
    "stuck in a holding pattern",
    "i need david",
    "i need david's input",
)

# Tokens to recognise as external dependencies. Order matters — more specific first.
_DEPENDENCY_PATTERNS = [
    re.compile(r"https?://[^\s\)\]\"']+"),
    re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b"),
    re.compile(r"\b/[\w./_-]+\.(?:py|json|sh|yml|yaml|md|txt)\b"),
    re.compile(r"\bConnection (?:refused|reset|timed out)\b", re.IGNORECASE),
    re.compile(r"\bTimeout\b", re.IGNORECASE),
    re.compile(r"\b(?:404|500|502|503|504) (?:Not Found|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)\b"),
]

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "this",
    "that", "with", "from", "they", "have", "been", "will", "would", "could",
    "should", "about", "into", "than", "them", "then", "when", "what", "which",
    "their", "there", "these", "those", "more", "some", "only", "other", "also",
    "now", "just", "very", "type", "model", "models", "your", "yours", "mine",
    "i'm", "i've", "i'll", "i'd", "let", "let's", "ok", "okay", "yeah", "yes",
    "no", "is", "it", "in", "on", "at", "to", "of", "as", "be", "by", "an",
    "or", "if", "so", "do", "did", "does", "was", "were", "has", "had",
    "next", "first", "second", "third",
}


def _keywords(text: str) -> set:
    """Extract significant lowercase tokens (3+ chars, not stopwords)."""
    if not text:
        return set()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_dependencies(text: str) -> set:
    """Pull out URLs, IPs, file paths, error markers from a chunk of text."""
    if not text:
        return set()
    deps = set()
    for pat in _DEPENDENCY_PATTERNS:
        for m in pat.findall(text):
            deps.add(m.lower() if isinstance(m, str) else str(m).lower())
    return deps


def _assistant_turns(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only the assistant_turn entries from a transcript slice."""
    return [e for e in entries if e.get("type") == "assistant_turn"]


def check_topic_overlap(entries: List[Dict[str, Any]]) -> Optional[str]:
    """
    Rule 1: Topic similarity. Last 3 assistant turns have >55% keyword overlap.
    """
    ats = _assistant_turns(entries)[-TOPIC_OVERLAP_WINDOW:]
    if len(ats) < TOPIC_OVERLAP_WINDOW:
        return None
    keyword_sets = [_keywords(a.get("content") or "") for a in ats]
    # Compute average pairwise jaccard
    pairs = 0
    total = 0.0
    for i in range(len(keyword_sets)):
        for j in range(i + 1, len(keyword_sets)):
            total += _jaccard(keyword_sets[i], keyword_sets[j])
            pairs += 1
    if pairs == 0:
        return None
    avg = total / pairs
    if avg >= TOPIC_OVERLAP_THRESHOLD:
        return (
            f"Topic loop: last {TOPIC_OVERLAP_WINDOW} assistant turns have "
            f"{avg:.0%} keyword overlap (threshold {TOPIC_OVERLAP_THRESHOLD:.0%})"
        )
    return None


def check_repeated_dependency(entries: List[Dict[str, Any]]) -> Optional[str]:
    """
    Rule 2: Same external dependency (URL, IP, file, error) appears in
    DEPENDENCY_REPEAT_THRESHOLD+ consecutive assistant turns.
    """
    ats = _assistant_turns(entries)[-DEPENDENCY_REPEAT_WINDOW:]
    if len(ats) < DEPENDENCY_REPEAT_THRESHOLD:
        return None
    per_turn_deps = [_extract_dependencies(a.get("content") or "") for a in ats]
    # Find any dependency that shows up in THRESHOLD+ of these turns
    counter = Counter()
    for deps in per_turn_deps:
        for d in deps:
            counter[d] += 1
    for dep, count in counter.most_common(3):
        if count >= DEPENDENCY_REPEAT_THRESHOLD:
            return (
                f"Repeated dependency: '{dep[:80]}' appears in {count} of the last "
                f"{len(ats)} assistant turns"
            )
    return None


def check_repeated_tool_calls(entries: List[Dict[str, Any]]) -> Optional[str]:
    """
    Rule 3: Same tool called TOOL_REPEAT_THRESHOLD+ times in the last
    TOOL_REPEAT_WINDOW assistant turns with similar arg signatures.
    """
    ats = _assistant_turns(entries)[-TOOL_REPEAT_WINDOW:]
    if len(ats) < TOOL_REPEAT_THRESHOLD:
        return None
    sig_counter = Counter()
    for a in ats:
        for tc in a.get("tool_calls") or []:
            name = tc.get("name", "")
            args = (tc.get("args") or "")[:60]  # short prefix to capture similarity
            sig_counter[(name, args)] += 1
    for (name, args), count in sig_counter.most_common(3):
        if count >= TOOL_REPEAT_THRESHOLD:
            return (
                f"Repeated tool: {name}({args[:40]}...) called {count} times in "
                f"the last {len(ats)} turns"
            )
    return None


def check_blocked_without_hitl(entries: List[Dict[str, Any]]) -> Optional[str]:
    """
    Rule 4: Sara explicitly says she's blocked / waiting for David in 2+ of the
    last 3 assistant turns, but never called request_human_input in those turns.
    """
    ats = _assistant_turns(entries)[-BLOCKED_LANGUAGE_WINDOW:]
    if len(ats) < 2:
        return None
    blocked_count = 0
    called_hitl = False
    matched_phrases = []
    for a in ats:
        content = (a.get("content") or "").lower()
        for phrase in _BLOCKED_PHRASES:
            if phrase in content:
                blocked_count += 1
                matched_phrases.append(phrase)
                break  # one match per turn is enough
        for tc in a.get("tool_calls") or []:
            if tc.get("name") in ("request_human_input", "human_input_request"):
                called_hitl = True
    if blocked_count >= 2 and not called_hitl:
        return (
            f"Sara says she's blocked {blocked_count}x in the last {len(ats)} "
            f"turns ({matched_phrases[0]!r}) but never called request_human_input"
        )
    return None


def evaluate(turn_count: int, recent_entries: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """
    Run all watchdog rules. Returns (tripped, reason). First rule wins.

    Args:
        turn_count: current session turn counter (used to gate early audits)
        recent_entries: last ~12 transcript entries (mix of user/assistant/tool_result)
    """
    if turn_count < MIN_TURNS_BEFORE_WATCHDOG:
        return False, None

    for rule in (
        check_blocked_without_hitl,   # most actionable, check first
        check_repeated_dependency,
        check_topic_overlap,
        check_repeated_tool_calls,
    ):
        try:
            reason = rule(recent_entries)
        except Exception as e:
            logger.debug(f"Watchdog rule {rule.__name__} errored: {e}")
            continue
        if reason:
            return True, reason

    return False, None
