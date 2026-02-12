"""
PKG Extraction Service

Extracts personal knowledge about David from conversations using LLM analysis.
Two modes:
- Deep extraction (dream cycle): Processes full day of conversations
- Lightweight extraction (subconscious cycle): Processes last 2 hours, conservative
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from app.core.llm import get_background_llm_client
from app.services.personal_knowledge_graph import personal_kg

logger = logging.getLogger(__name__)

DEEP_EXTRACTION_PROMPT = """You are an analyst extracting personal knowledge about David from his conversations with Sara (his AI assistant).

Given this day of conversations, extract facts about David's life, preferences, routines, goals, relationships, health, and places.

For each fact, classify as one of these types:
- **Person**: Someone David knows (name, relationship_to_david, notes)
- **Preference**: Something David likes/dislikes (domain, key, value, strength: love/like/dislike/hate)
- **Routine**: A recurring activity (activity, typical_time, day_of_week, frequency: daily/weekly/monthly/occasional)
- **Goal**: Something David is working toward (description, status: active/completed/abandoned, target_date, progress_notes)
- **Interest**: A topic David cares about (topic, depth: surface/moderate/deep, related_topics)
- **Health**: A health/wellness metric (metric, current_value, trend: improving/stable/declining, notes)
- **Place**: A significant location (name, type: home/work/gym/restaurant/other, address, significance)
- **Fact**: Anything else important (subject, predicate, object, category)

For each extracted fact, provide:
1. `type`: The classification above
2. `properties`: The type-specific properties
3. `confidence`: 0.0-1.0 (how certain are you this is accurate?)
   - 1.0: David explicitly stated this ("I love coffee")
   - 0.8: Strongly implied ("ordering my usual black coffee again")
   - 0.6: Reasonably inferred from context
   - 0.4: Weak inference, needs confirmation
4. `source_quote`: The conversation excerpt that supports this (brief)
5. `is_update`: true if this updates/changes a previously known fact (e.g., "I actually prefer tea now")

Return a JSON array. Only include genuinely useful personal knowledge, not transient conversation topics.

Example output:
```json
[
  {
    "type": "Preference",
    "properties": {"domain": "food", "key": "coffee", "value": "black, no sugar", "strength": "love"},
    "confidence": 0.95,
    "source_quote": "You know I love my black coffee",
    "is_update": false
  },
  {
    "type": "Routine",
    "properties": {"activity": "goes to gymnastics", "typical_time": "7pm", "day_of_week": "Wednesday", "frequency": "weekly"},
    "confidence": 0.85,
    "source_quote": "heading to gymnastics tonight like usual",
    "is_update": false
  }
]
```

CONVERSATIONS:
{conversations}"""

LIGHTWEIGHT_EXTRACTION_PROMPT = """Extract only EXPLICIT factual statements David made about himself in these recent messages.

Be very conservative — only extract facts where David directly stated something (confidence > 0.8).
Do NOT infer or guess. Only capture clear, direct statements.

Types: Person, Preference, Routine, Goal, Interest, Health, Place, Fact
(Same property schemas as before)

Return a JSON array. If nothing is explicitly stated, return [].

Example:
David says "I just started learning piano" →
```json
[{"type": "Interest", "properties": {"topic": "piano", "depth": "surface"}, "confidence": 0.9, "source_quote": "I just started learning piano"}]
```

David says "how's the weather?" → [] (no personal fact)

RECENT MESSAGES:
{messages}"""


class PKGExtractor:
    """Extracts personal knowledge from conversations for the PKG"""

    def __init__(self):
        self.llm_client = None

    def _ensure_llm(self):
        if self.llm_client is None:
            self.llm_client = get_background_llm_client()

    async def deep_extract(
        self,
        conversation_text: str,
        user_id: str,
        existing_contradictions: bool = True
    ) -> Dict[str, Any]:
        """
        Deep extraction for dream cycle — processes full day of conversations.

        Returns:
            Dict with 'extracted', 'contradictions', 'stats'
        """
        self._ensure_llm()

        if not conversation_text or len(conversation_text.strip()) < 50:
            return {"extracted": [], "contradictions": [], "stats": {"total": 0}}

        # Truncate very long conversations to avoid context limits
        max_chars = 15000
        if len(conversation_text) > max_chars:
            conversation_text = conversation_text[:max_chars] + "\n...(truncated)"

        prompt = DEEP_EXTRACTION_PROMPT.format(conversations=conversation_text)

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You extract structured personal knowledge from conversations. Always respond with valid JSON arrays only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=3000
            )

            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            facts = self._parse_json_response(content)

            if not facts:
                logger.info("PKG Extractor: No facts extracted from deep analysis")
                return {"extracted": [], "contradictions": [], "stats": {"total": 0}}

            # Process each extracted fact
            results = []
            contradictions = []

            for fact in facts:
                fact_type = fact.get("type", "Fact")
                properties = fact.get("properties", {})
                confidence = min(max(fact.get("confidence", 0.5), 0.1), 0.99)
                is_update = fact.get("is_update", False)

                # Check for contradictions if enabled
                if existing_contradictions and not is_update:
                    existing_conflicts = personal_kg.detect_contradictions(fact_type, properties)
                    if existing_conflicts:
                        contradictions.append({
                            "new_fact": fact,
                            "existing_conflicts": existing_conflicts
                        })

                # Determine source
                source = "dream_extraction"
                if confidence >= 0.9:
                    source = "explicit_statement"

                # Handle updates (supersede existing facts)
                if is_update and existing_contradictions:
                    conflicts = personal_kg.detect_contradictions(fact_type, properties)
                    for conflict in conflicts:
                        old_id = conflict.get("pkg_id")
                        if old_id:
                            personal_kg.supersede_fact(
                                old_id, properties, fact_type,
                                confidence=confidence, source=source
                            )

                # Upsert the fact
                pkg_id = personal_kg.upsert_fact(
                    fact_type=fact_type,
                    properties=properties,
                    confidence=confidence,
                    source=source
                )

                if pkg_id:
                    results.append({
                        "pkg_id": pkg_id,
                        "type": fact_type,
                        "confidence": confidence,
                        "source_quote": fact.get("source_quote", ""),
                        "is_update": is_update
                    })

            stats = {
                "total": len(results),
                "by_type": {},
                "avg_confidence": sum(r["confidence"] for r in results) / len(results) if results else 0
            }
            for r in results:
                stats["by_type"][r["type"]] = stats["by_type"].get(r["type"], 0) + 1

            logger.info(f"PKG Extractor: Deep extraction found {len(results)} facts, "
                       f"{len(contradictions)} contradictions")

            return {
                "extracted": results,
                "contradictions": contradictions,
                "stats": stats
            }

        except Exception as e:
            logger.error(f"PKG Extractor: Deep extraction failed: {e}")
            return {"extracted": [], "contradictions": [], "stats": {"total": 0, "error": str(e)}}

    async def lightweight_extract(
        self,
        messages: List[Dict[str, str]],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Lightweight extraction for subconscious cycle — only explicit statements.

        Args:
            messages: Recent conversation messages [{"role": "user", "content": "..."}]
            user_id: The user's ID

        Returns:
            Dict with 'extracted' and 'stats'
        """
        self._ensure_llm()

        # Only look at user messages
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return {"extracted": [], "stats": {"total": 0}}

        messages_text = "\n".join(
            f"David: {m['content']}" for m in user_messages
        )

        if len(messages_text.strip()) < 20:
            return {"extracted": [], "stats": {"total": 0}}

        # Truncate if needed
        if len(messages_text) > 5000:
            messages_text = messages_text[:5000] + "\n...(truncated)"

        prompt = LIGHTWEIGHT_EXTRACTION_PROMPT.format(messages=messages_text)

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You extract only explicit, high-confidence personal facts. Always respond with valid JSON arrays only. Return [] if nothing qualifies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500
            )

            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            facts = self._parse_json_response(content)

            if not facts:
                return {"extracted": [], "stats": {"total": 0}}

            results = []
            for fact in facts:
                confidence = min(max(fact.get("confidence", 0.5), 0.1), 0.99)

                # Lightweight mode: only keep high-confidence facts
                if confidence < 0.8:
                    continue

                fact_type = fact.get("type", "Fact")
                properties = fact.get("properties", {})

                pkg_id = personal_kg.upsert_fact(
                    fact_type=fact_type,
                    properties=properties,
                    confidence=confidence,
                    source="subconscious_extraction" if confidence < 0.9 else "explicit_statement"
                )

                if pkg_id:
                    results.append({
                        "pkg_id": pkg_id,
                        "type": fact_type,
                        "confidence": confidence
                    })

            logger.info(f"PKG Extractor: Lightweight extraction found {len(results)} facts")

            return {
                "extracted": results,
                "stats": {"total": len(results)}
            }

        except Exception as e:
            logger.error(f"PKG Extractor: Lightweight extraction failed: {e}")
            return {"extracted": [], "stats": {"total": 0, "error": str(e)}}

    def _parse_json_response(self, content: str) -> List[Dict]:
        """Parse LLM response as JSON array, handling common formatting issues"""
        if not content:
            return []

        # Try direct parse
        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            return []
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        if "```" in content:
            try:
                json_str = content.split("```json")[-1].split("```")[0].strip()
                if not json_str:
                    json_str = content.split("```")[-2].strip()
                result = json.loads(json_str)
                if isinstance(result, list):
                    return result
            except (json.JSONDecodeError, IndexError):
                pass

        # Try finding array brackets
        try:
            start = content.index("[")
            end = content.rindex("]") + 1
            result = json.loads(content[start:end])
            if isinstance(result, list):
                return result
        except (ValueError, json.JSONDecodeError):
            pass

        logger.warning(f"PKG Extractor: Could not parse JSON from response: {content[:200]}...")
        return []


# Singleton instance
pkg_extractor = PKGExtractor()
