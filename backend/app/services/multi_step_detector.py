"""
Multi-Step Task Detector — identifies requests that need orchestrated tool chaining.

Detects patterns like:
  "Check if Amanda's free Friday, find an Italian restaurant, make a reservation"
  "First look up X, then do Y with the result"

No LLM needed — uses pattern matching for speed.
"""

import re
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    description: str
    tool_categories: List[str]
    depends_on: List[int]  # indices of prior steps this depends on


@dataclass
class MultiStepPlan:
    is_multi_step: bool
    steps: List[TaskStep]
    original_query: str
    confidence: float


# Sequential connectors that indicate multi-step intent
_SEQUENTIAL_PATTERNS = [
    r'\b(?:then|after that|once .+ (?:is|are) done|next|and then)\b',
    r'\b(?:first|second|finally|lastly)\b',
    r'\b(?:if (?:she|he|they|it)(?:\'s| is| are) (?:free|available|busy))\b',
    r'\b(?:use (?:that|the result|those|it) to)\b',
    r'\b(?:with (?:that|the result|those|what you find))\b',
    r'\b(?:based on (?:that|the result|what))\b',
]

# Tool-category keywords
_TOOL_KEYWORDS = {
    "calendar": ["calendar", "schedule", "free", "available", "busy", "meeting", "event", "block time"],
    "email": ["email", "send", "reply", "forward", "message", "mail"],
    "web": ["search", "find", "look up", "restaurant", "weather", "flight", "book", "reserve"],
    "notes": ["note", "write down", "save", "document", "record"],
    "memory": ["remember", "recall", "what did", "last time"],
    "home": ["lights", "temperature", "thermostat", "lock", "door", "home"],
}


def detect_multi_step(query: str) -> MultiStepPlan:
    """
    Detect if a query requires multi-step orchestration.

    Returns a MultiStepPlan with steps and dependencies.
    """
    if not query or len(query) < 20:
        return MultiStepPlan(is_multi_step=False, steps=[], original_query=query, confidence=0.0)

    q = query.lower()

    # Count sequential pattern matches
    sequential_matches = sum(1 for p in _SEQUENTIAL_PATTERNS if re.search(p, q))

    # Count distinct tool categories referenced
    referenced_categories = set()
    for cat, keywords in _TOOL_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                referenced_categories.add(cat)
                break

    # Multi-step heuristic: sequential language + multiple tool categories
    is_multi = sequential_matches >= 1 and len(referenced_categories) >= 2
    if not is_multi:
        # Also detect comma-separated or "and"-connected actions
        action_verbs = len(re.findall(r'\b(?:check|find|search|book|send|create|look up|make|set up|get)\b', q))
        if action_verbs >= 2 and len(referenced_categories) >= 2:
            is_multi = True

    if not is_multi:
        return MultiStepPlan(is_multi_step=False, steps=[], original_query=query, confidence=0.0)

    # Decompose into steps
    steps = _decompose_steps(query, referenced_categories)
    confidence = min(0.9, 0.4 + 0.15 * sequential_matches + 0.1 * len(referenced_categories))

    return MultiStepPlan(
        is_multi_step=True,
        steps=steps,
        original_query=query,
        confidence=confidence,
    )


def _decompose_steps(query: str, categories: set) -> List[TaskStep]:
    """Split a multi-step query into ordered task steps."""
    steps = []

    # Try splitting on sequential connectors
    parts = re.split(r'\b(?:then|,\s*then|after that|,\s*and(?:\s+then)?|;\s*)\b', query, flags=re.IGNORECASE)

    if len(parts) >= 2:
        for i, part in enumerate(parts):
            part = part.strip().strip(",").strip()
            if len(part) < 5:
                continue
            cats = _detect_categories(part)
            deps = [i - 1] if i > 0 else []
            steps.append(TaskStep(description=part, tool_categories=cats, depends_on=deps))
    else:
        # Can't split cleanly — create steps per category
        for cat in sorted(categories):
            steps.append(TaskStep(
                description=f"{cat} action from: {query[:100]}",
                tool_categories=[cat],
                depends_on=[len(steps) - 1] if steps else [],
            ))

    return steps


def _detect_categories(text: str) -> List[str]:
    """Detect which tool categories a text segment references."""
    t = text.lower()
    cats = []
    for cat, keywords in _TOOL_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                cats.append(cat)
                break
    return cats or ["general"]
