"""
Query Router — classifies queries as factual (PKG) or episodic (memory).

Routes queries to the optimal data source:
  - PKG for factual questions about preferences, people, routines, goals
  - Episodic memory for temporal/event-based questions
  - Both for ambiguous queries

No LLM needed — uses keyword/pattern matching for speed.
"""

import re
import logging
from enum import Enum
from typing import Tuple

logger = logging.getLogger(__name__)


class QueryTarget(Enum):
    PKG = "pkg"           # Factual: preferences, people, routines
    EPISODIC = "episodic"  # Events, conversations, temporal
    BOTH = "both"          # Ambiguous — query both and merge


# Patterns that strongly indicate factual/PKG queries
_PKG_PATTERNS = [
    # Preferences
    r"\b(?:do i|does \w+ )?(?:like|prefer|enjoy|hate|love|dislike)\b",
    r"\bmy (?:favorite|favourite|preferred)\b",
    r"\bwhat(?:'s| is) my (?:favorite|preferred)\b",

    # People/relationships
    r"\b(?:who is|who's)\b",
    r"\b(?:amanda|wife|husband|partner|mom|dad|brother|sister)'?s?\b.*\b(?:birthday|job|work|email|phone|address)\b",

    # Routines/habits
    r"\b(?:when do i|how often do i|what time do i)\b",
    r"\bmy (?:schedule|routine|habit)\b",
    r"\b(?:what|where) do i (?:usually|normally|typically)\b",

    # Goals
    r"\bmy (?:goal|target|objective)\b",
    r"\bwhat am i (?:working on|trying to|learning)\b",

    # Places
    r"\b(?:where do i|my (?:home|work|office|gym|address))\b",

    # Direct factual
    r"\bwhat(?:'s| is) (?:my|david's|amanda's)\b",
    r"\bdo i (?:have|own|use)\b",
    r"\bhow (?:old|tall) (?:am i|is)\b",
]

# Patterns that strongly indicate temporal/episodic queries
_EPISODIC_PATTERNS = [
    r"\b(?:what happened|what did (?:we|i|you))\b",
    r"\b(?:last (?:time|week|month|tuesday|wednesday|monday|thursday|friday|saturday|sunday))\b",
    r"\b(?:yesterday|today|this morning|this week|this month)\b",
    r"\b(?:remember when|recall|that time)\b",
    r"\b(?:we (?:talked|discussed|mentioned|said))\b",
    r"\b(?:told (?:me|you)|you said|i said)\b",
    r"\b\d+ (?:days?|weeks?|months?) ago\b",
    r"\b(?:on|last) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:in (?:january|february|march|april|may|june|july|august|september|october|november|december))\b",
]


def classify_query(query: str) -> Tuple[QueryTarget, float]:
    """
    Classify a query as PKG-first, episodic-first, or both.

    Returns (target, confidence) where confidence is 0.0-1.0.
    """
    if not query:
        return QueryTarget.BOTH, 0.0

    q = query.lower().strip()

    pkg_score = 0
    episodic_score = 0

    for pattern in _PKG_PATTERNS:
        if re.search(pattern, q):
            pkg_score += 1

    for pattern in _EPISODIC_PATTERNS:
        if re.search(pattern, q):
            episodic_score += 1

    total = pkg_score + episodic_score
    if total == 0:
        return QueryTarget.BOTH, 0.3  # Low confidence, try both

    if pkg_score > episodic_score:
        confidence = min(0.9, 0.5 + 0.15 * pkg_score)
        return QueryTarget.PKG, confidence
    elif episodic_score > pkg_score:
        confidence = min(0.9, 0.5 + 0.15 * episodic_score)
        return QueryTarget.EPISODIC, confidence
    else:
        return QueryTarget.BOTH, 0.5
