"""
PKG Context Provider

Formats Personal Knowledge Graph data for injection into chat system prompts.
Produces natural language summaries rather than database dumps.
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from app.services.personal_knowledge_graph import (
    personal_kg,
    is_authoritative_health_copy,
    is_transient_health_text,
)

logger = logging.getLogger(__name__)

# Facts older than this get an explicit age suffix so the model can discount
# them ("noted 6 months ago") instead of reading a stale snapshot as current.
_STALE_AGE_THRESHOLD_DAYS = 21
# Transient Health states (sick/tired/sore/...) drop out of context entirely
# once they're this old without being reconfirmed.
_TRANSIENT_HEALTH_TTL_DAYS = 14
# Health facts get a far tighter staleness rule than the generic 21 days.
# A six-day-old "sleep_duration: 7.5 hours" rendered perfectly clean under the
# generic threshold, which is how a stale guess became indistinguishable from
# this morning's reading (2026-08-31 incident, D4). Anything about David's body
# older than two days carries its date.
_HEALTH_STALE_AGE_HOURS = 48


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(iso_value: Optional[str]) -> Optional[int]:
    dt = _parse_iso(iso_value)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _age_suffix(last_confirmed: Optional[str]) -> str:
    """' (noted 2026-02-23 — ~6 months ago, may be stale)' past the
    threshold; '' otherwise. Lets the model discount what it can see."""
    dt = _parse_iso(last_confirmed)
    if dt is None:
        return ""
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days < _STALE_AGE_THRESHOLD_DAYS:
        return ""
    months = age_days // 30
    age_str = f"~{months} month{'s' if months != 1 else ''} ago" if months >= 1 else f"~{age_days} days ago"
    return f" (noted {dt.date().isoformat()} — {age_str}, may be stale)"


def _health_age_suffix(last_confirmed: Optional[str]) -> str:
    """' (as of 2026-08-25, 6 days ago — not a current reading)' for anything
    older than 48h; '' otherwise. Every health line the model sees either is
    from today or says when it is from."""
    dt = _parse_iso(last_confirmed)
    if dt is None:
        return " (no date recorded — not a current reading)"
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if age_hours < _HEALTH_STALE_AGE_HOURS:
        return ""
    days = int(age_hours // 24)
    when = f"{days} day{'s' if days != 1 else ''} ago" if days >= 1 else f"{int(age_hours)}h ago"
    return f" (as of {dt.date().isoformat()}, {when} — not a current reading)"


class PKGContextProvider:
    """Provides formatted PKG context for chat injection"""

    async def get_relevant_context(
        self,
        user_id: str,
        message: str,
        intent: str = ""
    ) -> str:
        """
        Get PKG facts relevant to the current message, formatted as natural text.

        Tries semantic (embedding) search first for better recall (catches
        "espresso" when query is "coffee"), falls back to text CONTAINS matching.
        """
        try:
            # Try semantic search first (pgvector)
            facts = []
            try:
                facts = await personal_kg.query_semantic(message, limit=8, min_similarity=0.35)
            except Exception as e:
                from app.core.swallow import swallow
                await swallow(logger, "pkg_context_provider.query_semantic", e)

            # Fall back to text-based search if semantic returned nothing
            if not facts:
                topics = self._extract_topics(message)
                if not topics:
                    return self._get_brief_summary(max_facts=5)
                facts = personal_kg.query_relevant(topics, limit=8)

            if not facts:
                return ""

            return self._format_facts_natural(facts)

        except Exception as e:
            logger.warning(f"PKG context provider failed: {e}")
            return ""

    def get_david_summary_brief(self, user_id: str, max_facts: int = 8) -> str:
        """Get a brief summary for re-entry context"""
        return self._get_brief_summary(max_facts=max_facts)

    def _extract_topics(self, message: str) -> List[str]:
        """Extract searchable topics from a message"""
        if not message:
            return []

        message_lower = message.lower()
        topics = []

        # Extract named entities (capitalized words that aren't sentence starters)
        words = message.split()
        for i, word in enumerate(words):
            clean = re.sub(r'[^\w]', '', word)
            if clean and clean[0].isupper() and i > 0 and len(clean) > 2:
                topics.append(clean.lower())

        # Extract key noun phrases and domain terms
        domain_patterns = [
            # Food/drink
            (r'\b(coffee|tea|food|eat|meal|breakfast|lunch|dinner|cook|recipe)\b', None),
            # Fitness
            (r'\b(gym|workout|exercise|run|fitness|gymnastics|weight|training)\b', None),
            # Work
            (r'\b(work|job|project|meeting|code|develop|build)\b', None),
            # Health
            (r'\b(sleep|energy|tired|health|stress|recovery|rest)\b', None),
            # Goals
            (r'\b(goal|target|plan|achieve|progress|improve)\b', None),
            # Routines
            (r'\b(routine|schedule|usually|always|every|morning|evening|night)\b', None),
            # People
            (r'\b(friend|family|wife|husband|partner|colleague|boss|mom|dad)\b', None),
            # Places
            (r'\b(home|office|gym|restaurant|store|park)\b', None),
            # Preferences
            (r'\b(like|love|prefer|favorite|hate|dislike|enjoy)\b', None),
        ]

        for pattern, _ in domain_patterns:
            matches = re.findall(pattern, message_lower)
            topics.extend(matches)

        # Also add significant words (4+ chars, not common stop words)
        stop_words = {
            'that', 'this', 'with', 'have', 'from', 'they', 'been', 'said',
            'each', 'which', 'their', 'will', 'other', 'about', 'many',
            'then', 'them', 'these', 'some', 'would', 'make', 'like',
            'just', 'over', 'such', 'take', 'than', 'very', 'what',
            'could', 'does', 'should', 'your', 'when', 'here', 'there',
            'know', 'want', 'think', 'tell', 'going', 'doing',
        }
        for word in words:
            clean = re.sub(r'[^\w]', '', word).lower()
            if len(clean) >= 5 and clean not in stop_words:
                topics.append(clean)

        # Deduplicate while preserving order
        seen = set()
        unique_topics = []
        for t in topics:
            if t not in seen:
                seen.add(t)
                unique_topics.append(t)

        return unique_topics[:6]  # Limit to 6 topics for query efficiency

    def _format_facts_natural(self, facts: List[dict]) -> str:
        """Format PKG facts as natural language for system prompt injection"""
        if not facts:
            return ""

        lines = []
        for fact in facts:
            fact_type = fact.get("type", "Unknown")
            conf = fact.get("confidence", 0)
            confirmed = fact.get("times_confirmed", 1)

            conf_label = "high confidence" if conf > 0.8 else "moderate confidence" if conf > 0.6 else "low confidence"
            line = self._fact_to_sentence(fact_type, fact)
            if line:
                lines.append(f"- {line} ({conf_label}, confirmed {confirmed}x)")

        if not lines:
            return ""

        return (
            "\n\n## What Sara Knows About David (relevant to this conversation)\n"
            + "\n".join(lines)
            + "\n"
        )

    def _get_brief_summary(self, max_facts: int = 8) -> str:
        """Get a brief PKG summary with top-confidence facts"""
        try:
            summary = personal_kg.get_david_summary(max_facts=max_facts)
            return f"\n\n{summary}\n" if summary else ""
        except Exception as e:
            logger.warning(f"PKG brief summary failed: {e}")
            return ""

    def _fact_to_sentence(self, fact_type: str, props: dict) -> str:
        """Convert a single fact to a natural language sentence"""
        if fact_type == "Person":
            name = props.get("name", "someone")
            rel = props.get("relationship_to_david", "")
            return f"David knows {name}" + (f" ({rel})" if rel else "")
        elif fact_type == "Preference":
            value = props.get("value", "")
            domain = props.get("domain", "")
            strength = props.get("strength", "likes")
            verb = {"love": "loves", "like": "likes", "dislike": "dislikes", "hate": "hates"}.get(strength, "prefers")
            return f"David {verb} {value}" + (f" [{domain}]" if domain else "")
        elif fact_type == "Routine":
            activity = props.get("activity", "")
            day = props.get("day_of_week", "")
            time = props.get("typical_time", "")
            freq = props.get("frequency", "")
            parts = [f"David {activity}"]
            if day:
                parts.append(f"on {day}s")
            if time:
                parts.append(f"around {time}")
            if freq:
                parts.append(f"({freq})")
            return " ".join(parts)
        elif fact_type == "Goal":
            desc = props.get("description", "")
            status = props.get("status", "active")
            return f"David's goal: {desc} (status: {status})" + _age_suffix(props.get("last_confirmed"))
        elif fact_type == "Interest":
            topic = props.get("topic", "")
            depth = props.get("depth", "")
            return f"David is interested in {topic}" + (f" ({depth} interest)" if depth else "")
        elif fact_type == "Health":
            metric = props.get("metric", "")
            value = props.get("current_value", "")
            trend = props.get("trend", "")
            last_confirmed = props.get("last_confirmed")
            expires_at = props.get("expires_at")
            # Raw wins, always. `health_metric` is the only authority for a
            # number about David's body; a graph copy carries no recorded_at
            # and cannot be corrected. `upsert_fact` refuses to mint these now,
            # but legacy nodes are still in Neo4j — they die here on read, in
            # the one shared formatter, so every caller (chat, voice, brief,
            # memory.recall) gets the same answer.
            if is_authoritative_health_copy(metric, value):
                return ""
            transient = bool(expires_at) or is_transient_health_text(metric, value)
            if transient:
                if expires_at:
                    expiry_dt = _parse_iso(expires_at)
                    stale = expiry_dt is not None and datetime.now(timezone.utc) > expiry_dt
                else:
                    age = _age_days(last_confirmed)
                    stale = age is not None and age > _TRANSIENT_HEALTH_TTL_DAYS
                if stale:
                    return ""  # transient state, unconfirmed past its TTL — drop entirely
            sentence = f"David's {metric}: {value}" + (f" (trending {trend})" if trend else "")
            return sentence + _health_age_suffix(last_confirmed)
        elif fact_type == "Place":
            name = props.get("name", "")
            ptype = props.get("type", "")
            return f"David frequents {name}" + (f" ({ptype})" if ptype else "")
        elif fact_type == "Fact":
            subj = props.get("subject", "David")
            pred = props.get("predicate", "")
            obj = props.get("object", "")
            return f"{subj} {pred} {obj}" + _age_suffix(props.get("last_confirmed"))
        return ""


# Singleton
pkg_context = PKGContextProvider()
