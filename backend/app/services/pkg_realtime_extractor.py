"""
Real-time PKG extraction — detects explicit factual statements in user messages.

Runs pattern matching (no LLM) to catch obvious facts:
  "Amanda's birthday is March 15" → PKG_Person update
  "I prefer tea now" → PKG_Preference update
  "My gym is Planet Fitness on Oak Street" → PKG_Place update

For ambiguous or complex statements, defers to the periodic LLM-based extraction.
"""

import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Patterns for explicit factual statements
_FACT_PATTERNS = [
    # Preferences: "I prefer/like/love/hate X"
    (r"\bi (?:actually )?(?:prefer|like|love|enjoy|hate|dislike)\s+(.+?)(?:\.|$|,| now| these days| lately)",
     "preference", 0.85),

    # People facts: "X's birthday is Y", "X works at Y"
    (r"(\w+)(?:'s| 's) birthday is (.+?)(?:\.|$|,)",
     "person_birthday", 0.9),
    (r"(\w+) (?:works at|works for|is at) (.+?)(?:\.|$|,)",
     "person_work", 0.8),

    # Corrections: "actually it's X", "no, I meant X"
    (r"\b(?:actually|no,?\s*) (?:it's|it is|i meant|i mean|my .+ is) (.+?)(?:\.|$|,)",
     "correction", 0.9),

    # Schedule/routine: "I usually X on Y", "I go to X every Y"
    (r"\bi (?:usually|normally|always|typically) (.+?)(?:\.|$)",
     "routine", 0.75),
    (r"\bi (?:go to|visit|attend) (.+?) (?:every|on) (.+?)(?:\.|$)",
     "routine_place", 0.8),

    # Location: "My X is at/on Y"
    (r"\bmy (\w+) is (?:at|on|in) (.+?)(?:\.|$|,)",
     "place", 0.8),

    # Goals: "I'm trying to X", "my goal is X"
    (r"\b(?:i'm trying to|my goal is|i want to) (.+?)(?:\.|$)",
     "goal", 0.7),
]


def extract_realtime_facts(message: str) -> List[Dict[str, Any]]:
    """
    Extract facts from a single user message using pattern matching.

    Returns list of dicts with: type, value, confidence, raw_match
    """
    if not message or len(message) < 10:
        return []

    facts = []
    msg = message.strip()

    for pattern, fact_type, confidence in _FACT_PATTERNS:
        matches = re.finditer(pattern, msg, re.IGNORECASE)
        for match in matches:
            value = match.group(0).strip().rstrip(".,;!")
            if len(value) > 5:
                facts.append({
                    "type": fact_type,
                    "value": value,
                    "confidence": confidence,
                    "raw_match": match.group(0),
                })

    return facts


async def process_message_for_pkg(user_id: str, message: str):
    """
    Process a user message for real-time PKG updates.
    Only upserts high-confidence explicit facts.
    """
    facts = extract_realtime_facts(message)
    if not facts:
        return

    high_confidence = [f for f in facts if f["confidence"] >= 0.8]
    if not high_confidence:
        return

    try:
        from app.services.personal_knowledge_graph import personal_kg

        # Map internal fact types to PKG node types
        _TYPE_MAP = {
            "preference": "Preference",
            "person_birthday": "Person",
            "person_work": "Person",
            "routine": "Routine",
            "routine_place": "Routine",
            "correction": "Fact",
            "place": "Place",
            "goal": "Goal",
        }

        for fact in high_confidence:
            fact_type = _TYPE_MAP.get(fact["type"], "Fact")
            value = fact["value"]
            source = "user_correction" if fact["type"] == "correction" else "explicit_statement"

            # For corrections, try to find and supersede the old fact first
            if fact["type"] == "correction":
                try:
                    related = await personal_kg.query_semantic(value, limit=1) \
                        if hasattr(personal_kg, 'query_semantic') else []
                    for old_fact in related:
                        if old_fact.get("similarity", 0) > 0.6 and old_fact.get("pkg_id"):
                            personal_kg.supersede_fact(
                                old_pkg_id=old_fact["pkg_id"],
                                new_properties={"value": value},
                                fact_type=fact_type,
                                confidence=fact["confidence"],
                                source=source,
                            )
                            logger.info(f"PKG real-time: superseded fact {old_fact['pkg_id']} with correction")
                            continue
                except Exception as e:
                    logger.debug(f"PKG supersede attempt failed: {e}")

            # Normal upsert (synchronous call — no await)
            personal_kg.upsert_fact(
                fact_type=fact_type,
                properties={"value": value},
                confidence=fact["confidence"],
                source=source,
            )

        logger.info(f"PKG real-time: extracted {len(high_confidence)} facts from message")
    except Exception as e:
        logger.debug(f"PKG real-time extraction failed: {e}")
