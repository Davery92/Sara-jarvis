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


_MENTION_STOPWORDS = {
    "the", "and", "for", "our", "your", "team", "support", "info", "sales",
    "hello", "hi", "sincerely", "regards", "thanks", "thank", "best", "dear",
}


def _mentions_name(message: str, name: str) -> bool:
    """True if `name`'s first token appears as a genuine reference in
    `message` — a mid-sentence capitalized word, not just a lowercase
    substring hit. Without this, a person named "The Quo Team" (a real row
    from the D.1 email-history seed) matches on the ordinary word "the" in
    ANY message, since its first token is "the" — this caught that exact
    bug during testing before it shipped."""
    first_token = name.split()[0].strip() if name else ""
    if len(first_token) < 3 or first_token.lower() in _MENTION_STOPWORDS:
        return False
    # Sentence-initial capitalization is orthographic, not a signal — require
    # the match at a NON-initial word position (same reasoning as
    # deliberation_gate._has_proper_noun, which caught an analogous bug
    # earlier this session).
    words = re.findall(r"[A-Za-z']+", message)
    for word in words[1:]:
        if word.lower() == first_token.lower() and word[0].isupper():
            return True
    return False


async def bump_mentioned_people(user_id: str, message: str) -> int:
    """SARA_UNLEASHED Phase D.3: bump a known person's mention_count/
    last_interaction_at the moment their name appears in chat, instead of
    waiting for the 2x-daily consolidation pass (pkg_extractor.deep_extract/
    lightweight_extract already do this bump — just too slowly for
    'reconnect_overdue' to reflect today's conversation). Deliberately
    cheap: a name-list match against people already in the `person` table,
    not LLM extraction — that stays the periodic pass's job. Returns the
    number of people bumped."""
    if not message or len(message) < 3:
        return 0

    try:
        from sqlalchemy import text
        from app.db.session import get_async_session_factory
        from app.services.person_service import bump_person_mention

        factory = get_async_session_factory()
        bumped = 0
        async with factory() as db:
            rows = (await db.execute(text("""
                SELECT canonical_name, aliases FROM person WHERE user_id = :uid
            """), {"uid": user_id})).fetchall()

            seen_this_message = set()
            for canonical_name, aliases in rows:
                if canonical_name in seen_this_message:
                    continue
                candidates = [canonical_name] + list(aliases or [])
                if any(_mentions_name(message, c) for c in candidates if c):
                    await bump_person_mention(db, user_id, canonical_name)
                    seen_this_message.add(canonical_name)
                    bumped += 1
            if bumped:
                await db.commit()
        return bumped
    except Exception as e:
        logger.debug(f"Real-time person mention bump failed: {e}")
        return 0


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
