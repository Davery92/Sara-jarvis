"""
PKG Extraction Service

Extracts personal knowledge about David from conversations using LLM analysis.
Three modes:
- Deep extraction (dream cycle): Processes full day of conversations
- Lightweight extraction (subconscious cycle): Processes last 2 hours, conservative
- Behavioral extraction (weekly): Infers interests/routines from engagement patterns
"""

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from app.core.llm import get_background_llm_client
from app.services.personal_knowledge_graph import personal_kg

logger = logging.getLogger(__name__)

# Redis key for tracking last behavioral extraction run
BEHAVIORAL_EXTRACTION_KEY = "sara:pkg:last_behavioral_extraction"

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

        prompt = DEEP_EXTRACTION_PROMPT.replace("{conversations}", conversation_text)

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
            logger.info(f"PKG Extractor: LLM response length={len(content)}, preview={content[:200]!r}")
            facts = self._parse_json_response(content)

            if not facts:
                logger.info("PKG Extractor: No facts extracted from deep analysis")
                return {"extracted": [], "contradictions": [], "stats": {"total": 0}}

            # Process each extracted fact
            results = []
            contradictions = []

            for fact in facts:
                if not isinstance(fact, dict):
                    logger.warning(f"PKG Extractor: Skipping non-dict fact: {type(fact)} {str(fact)[:100]}")
                    continue
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

        prompt = LIGHTWEIGHT_EXTRACTION_PROMPT.replace("{messages}", messages_text)

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

    async def extract_from_behavior(self, user_id: str) -> Dict[str, Any]:
        """
        Behavioral extraction — infers PKG entries from engagement patterns.

        No LLM calls. Queries notification_log and episode tables to find:
        - Which notification categories David engages with most -> PKG_Interest
        - Frequently discussed topics (word frequency in last 30 days) -> PKG_Interest
        - Consistent response-time patterns -> PKG_Routine

        Rate-limited to run at most once per week (checks Redis timestamp).

        Returns:
            Dict with 'extracted' list and 'stats'
        """
        # Rate-limit check: only run weekly
        redis_conn = None
        try:
            import redis.asyncio as aioredis
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            redis_conn = await aioredis.from_url(redis_url, decode_responses=True)
            last_run = await redis_conn.get(BEHAVIORAL_EXTRACTION_KEY)
            if last_run:
                last_dt = datetime.fromisoformat(last_run)
                if (datetime.now(timezone.utc) - last_dt).days < 7:
                    logger.info("PKG Behavioral: Skipping — last run was less than 7 days ago")
                    return {"extracted": [], "stats": {"skipped": True, "reason": "rate_limited"}}
        except Exception as e:
            logger.debug(f"PKG Behavioral: Redis rate-limit check failed: {e}")
            # Continue anyway if Redis is down

        # Create a sync DB session for queries
        database_url = os.getenv("DATABASE_URL", "")
        if "asyncpg" in database_url:
            database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        elif "psycopg" in database_url:
            database_url = database_url.replace("postgresql+psycopg://", "postgresql://")

        try:
            from sqlalchemy import create_engine, text as sa_text
            from sqlalchemy.orm import sessionmaker as sync_sessionmaker
            engine = create_engine(database_url, echo=False)
            Session = sync_sessionmaker(bind=engine)
            session = Session()
        except Exception as e:
            logger.error(f"PKG Behavioral: DB connection failed: {e}")
            return {"extracted": [], "stats": {"error": str(e)}}

        results = []

        try:
            # ─── 1. Notification engagement patterns ───
            try:
                rows = session.execute(sa_text("""
                    SELECT category, COUNT(*) as total,
                           COUNT(*) FILTER (WHERE engaged = TRUE) as engaged_count
                    FROM notification_log
                    WHERE user_id = :uid
                      AND sent = TRUE
                      AND sent_at >= NOW() - INTERVAL '30 days'
                    GROUP BY category
                    HAVING COUNT(*) >= 3
                    ORDER BY COUNT(*) FILTER (WHERE engaged = TRUE) DESC
                """), {"uid": user_id}).fetchall()

                for row in rows:
                    category = row.category or "general"
                    total = row.total
                    engaged = row.engaged_count
                    engagement_rate = engaged / total if total > 0 else 0

                    # If David engages with >50% of notifications in a category,
                    # that's a signal of genuine interest
                    if engagement_rate >= 0.5 and engaged >= 3:
                        # Map notification categories to interests
                        # Common categories: health, security, social, schedule, check_in, home
                        interest_mapping = {
                            "health": "health and wellness tracking",
                            "security": "home security",
                            "social": "social connections",
                            "schedule": "time management",
                            "home": "smart home automation",
                        }
                        topic = interest_mapping.get(category, category)

                        confidence = min(0.6 + (engagement_rate * 0.2), 0.8)
                        pkg_id = personal_kg.upsert_fact(
                            fact_type="Interest",
                            properties={
                                "topic": topic,
                                "depth": "active" if engagement_rate > 0.7 else "moderate",
                                "category": "behavioral_inference",
                                "description": f"David regularly engages with {category} notifications ({engagement_rate:.0%} rate)",
                            },
                            confidence=confidence,
                            source="behavioral_inference",
                        )
                        if pkg_id:
                            results.append({
                                "pkg_id": pkg_id,
                                "type": "Interest",
                                "topic": topic,
                                "confidence": confidence,
                                "source_signal": f"notification engagement: {category} ({engaged}/{total})",
                            })
            except Exception as e:
                logger.debug(f"PKG Behavioral: Notification query failed: {e}")

            # ─── 2. Frequently discussed topics from episodes ───
            try:
                rows = session.execute(sa_text("""
                    SELECT content FROM episode
                    WHERE user_id = :uid
                      AND role = 'user'
                      AND content IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY created_at DESC
                    LIMIT 500
                """), {"uid": user_id}).fetchall()

                if rows:
                    # Extract meaningful words (4+ chars) and count frequency
                    word_counter = Counter()
                    # Stop words to exclude
                    stop_words = {
                        "that", "this", "with", "from", "have", "been", "will",
                        "would", "could", "should", "about", "which", "their",
                        "there", "what", "when", "where", "your", "just",
                        "like", "know", "make", "also", "well", "some",
                        "them", "than", "then", "into", "over", "such",
                        "more", "most", "much", "many", "each", "very",
                        "they", "here", "were", "being", "does", "doing",
                        "done", "going", "want", "need", "sure", "yeah",
                        "okay", "really", "think", "good", "thanks", "thank",
                        "please", "right", "thing", "things", "look", "help",
                        "can't", "don't", "it's", "i'm", "i've", "let's",
                        "didn't", "doesn't", "isn't", "aren't", "wasn't",
                        "weren't", "hadn't", "hasn't", "haven't", "won't",
                        "wouldn't", "couldn't", "shouldn't", "might", "still",
                    }

                    for row in rows:
                        content = row.content.lower()
                        # Extract words, skip short ones
                        words = re.findall(r'\b[a-z]{4,}\b', content)
                        # Filter stop words
                        words = [w for w in words if w not in stop_words]
                        word_counter.update(set(words))  # unique per message to avoid single-message spikes

                    # Topics mentioned in 5+ distinct messages in 30 days
                    frequent_topics = [
                        (word, count) for word, count in word_counter.most_common(30)
                        if count >= 5
                    ]

                    for topic, mention_count in frequent_topics[:10]:
                        # Check if this topic already has a PKG node
                        existing = personal_kg.query_relevant([topic], limit=1)
                        if existing:
                            continue  # Already known

                        confidence = min(0.5 + (mention_count / 50), 0.8)
                        pkg_id = personal_kg.upsert_fact(
                            fact_type="Interest",
                            properties={
                                "topic": topic,
                                "depth": "moderate" if mention_count >= 10 else "surface",
                                "category": "behavioral_inference",
                                "description": f"David discusses '{topic}' frequently ({mention_count} times in 30 days)",
                            },
                            confidence=confidence,
                            source="behavioral_inference",
                        )
                        if pkg_id:
                            results.append({
                                "pkg_id": pkg_id,
                                "type": "Interest",
                                "topic": topic,
                                "confidence": confidence,
                                "source_signal": f"mentioned in {mention_count} messages",
                            })
            except Exception as e:
                logger.debug(f"PKG Behavioral: Episode word frequency failed: {e}")

            # ─── 3. Response-time patterns (routine inference) ───
            try:
                rows = session.execute(sa_text("""
                    SELECT EXTRACT(HOUR FROM created_at) as hour,
                           COUNT(*) as msg_count
                    FROM episode
                    WHERE user_id = :uid
                      AND role = 'user'
                      AND created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY EXTRACT(HOUR FROM created_at)
                    HAVING COUNT(*) >= 10
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """), {"uid": user_id}).fetchall()

                if rows:
                    total_messages = sum(r.msg_count for r in rows)
                    for row in rows:
                        hour = int(row.hour)
                        count = row.msg_count
                        pct = count / total_messages if total_messages > 0 else 0

                        # Only create routine for strongly concentrated hours (>15% of messages)
                        if pct >= 0.15:
                            # Determine time label
                            if 6 <= hour < 10:
                                time_label = "morning"
                            elif 10 <= hour < 14:
                                time_label = "late morning/midday"
                            elif 14 <= hour < 18:
                                time_label = "afternoon"
                            elif 18 <= hour < 22:
                                time_label = "evening"
                            else:
                                time_label = "late night"

                            pkg_id = personal_kg.upsert_fact(
                                fact_type="Routine",
                                properties={
                                    "activity": f"active/chatting with Sara",
                                    "typical_time": f"{hour}:00",
                                    "frequency": "daily",
                                    "day_of_week": "any",
                                    "description": f"David is often active around {hour}:00 ({time_label}), with {pct:.0%} of recent messages",
                                },
                                confidence=min(0.6 + (pct * 0.3), 0.8),
                                source="behavioral_inference",
                            )
                            if pkg_id:
                                results.append({
                                    "pkg_id": pkg_id,
                                    "type": "Routine",
                                    "activity": f"active at {hour}:00 ({time_label})",
                                    "confidence": min(0.6 + (pct * 0.3), 0.8),
                                    "source_signal": f"{count} messages at hour {hour} ({pct:.0%})",
                                })
            except Exception as e:
                logger.debug(f"PKG Behavioral: Response time pattern failed: {e}")

        finally:
            session.close()
            engine.dispose()

        # Update rate-limit timestamp
        if redis_conn:
            try:
                await redis_conn.set(BEHAVIORAL_EXTRACTION_KEY, datetime.now(timezone.utc).isoformat())
            except Exception:
                pass

        stats = {
            "total": len(results),
            "by_type": {},
        }
        for r_item in results:
            t = r_item["type"]
            stats["by_type"][t] = stats["by_type"].get(t, 0) + 1

        logger.info(f"PKG Behavioral: Extracted {len(results)} facts from behavioral patterns")
        return {"extracted": results, "stats": stats}

    async def extract_from_acs_note(
        self,
        content: str,
        title: str,
        user_id: str = None,
    ) -> Dict[str, Any]:
        """
        Extract David-relevant facts from an ACS-authored note.

        Uses a lightweight prompt that only targets facts about David's life,
        not Sara's own observations or intellectual interests.
        """
        self._ensure_llm()

        if not content or len(content.strip()) < 50:
            return {"extracted": [], "stats": {"total": 0}}

        # Truncate long notes
        if len(content) > 5000:
            content = content[:5000] + "\n...(truncated)"

        prompt = (
            f"Sara (an AI assistant) wrote this note during autonomous exploration:\n\n"
            f"Title: {title}\n\n{content}\n\n"
            f"Extract ONLY facts about David (Sara's human) from this note. "
            f"Ignore Sara's own reflections, intellectual observations, or research summaries "
            f"that don't reveal something about David's life, preferences, routines, or goals.\n\n"
            f"Types: Person, Preference, Routine, Goal, Interest, Health, Place, Fact\n"
            f"Return a JSON array. If nothing about David is mentioned, return []."
        )

        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "Extract personal facts about David only. Return valid JSON arrays. Return [] if nothing qualifies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=1500,
            )

            resp_content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            facts = self._parse_json_response(resp_content)

            if not facts:
                return {"extracted": [], "stats": {"total": 0}}

            results = []
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                confidence = min(max(fact.get("confidence", 0.5), 0.1), 0.99)
                if confidence < 0.6:
                    continue

                fact_type = fact.get("type", "Fact")
                properties = fact.get("properties", {})

                pkg_id = personal_kg.upsert_fact(
                    fact_type=fact_type,
                    properties=properties,
                    confidence=confidence,
                    source="acs_note_extraction",
                )
                if pkg_id:
                    results.append({"pkg_id": pkg_id, "type": fact_type, "confidence": confidence})

            logger.info(f"PKG ACS note extraction: {len(results)} facts from '{title}'")
            return {"extracted": results, "stats": {"total": len(results)}}

        except Exception as e:
            logger.error(f"PKG ACS note extraction failed: {e}")
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
