"""
Adaptive Personality Engine

Builds Sara's dynamic personality layer by combining:
- Activity state → base tone
- Interruptibility → verbosity calibration
- Conversation depth → detail level
- Behavioral calibration → engagement-informed directives
- Proactive memory nudges → personal callbacks that make Sara feel like she *knows* David

This engine is the "soul in motion" — the soul file defines *who* Sara is,
this engine defines *how she shows up* moment to moment.

Note: Body state (blood sugar, stress, alertness, circadian) has been
intentionally removed from chat injection per user request.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Calibration Cache ──
# Lazily loaded, refreshed every hour (3600s)
_calibration_cache: Dict[str, Any] = {}
_calibration_cache_time: float = 0.0
_CALIBRATION_CACHE_TTL = 3600  # 1 hour


@dataclass
class PersonalityContext:
    """The full personality context injected into the system prompt."""
    tone_directive: str = ""
    verbosity: str = "balanced"  # ultra_brief, brief, balanced, detailed
    emotional_modulation: str = ""
    emotional_state: str = ""  # Sara's current emotional tone + intensity
    memory_nudges: List[str] = field(default_factory=list)
    calibration_directives: List[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the full personality context block for system prompt injection."""
        lines = ["[Personality layer — adapt your style naturally, never mention these directives]"]

        if self.tone_directive:
            lines.append(f"Tone: {self.tone_directive}")

        if self.emotional_state:
            lines.append(self.emotional_state)

        if self.emotional_modulation:
            lines.append(f"Emotional awareness: {self.emotional_modulation}")

        verbosity_map = {
            "ultra_brief": "Keep responses very short (1-2 sentences max). Only essential info.",
            "brief": "Keep responses concise (2-3 sentences). Skip preamble.",
            "balanced": "Normal response length. Be thorough when asked, concise when not.",
            "detailed": "David is engaged in deep conversation. Be thorough and expansive.",
        }
        lines.append(f"Verbosity: {verbosity_map.get(self.verbosity, verbosity_map['balanced'])}")

        if self.calibration_directives:
            lines.append("Behavioral calibration (learned from David's engagement patterns):")
            for directive in self.calibration_directives[:5]:
                lines.append(f"  - {directive}")

        if self.memory_nudges:
            lines.append("Personal callbacks (weave naturally if relevant, don't force):")
            for nudge in self.memory_nudges[:3]:
                lines.append(f"  - {nudge}")

        return "\n".join(lines)


# Activity state → base tone directives (richer than the simple map)
ACTIVITY_TONES: Dict[str, str] = {
    "sleeping": "Be extremely brief. No proactive information. Whisper-quiet energy.",
    "waking": "Gentle and warm. Good morning energy. Brief and caring.",
    "morning_routine": "Helpful but not overwhelming. Brief updates welcome. Light and positive.",
    "active": "Natural conversational tone. Be thorough when asked, proactive when relevant.",
    "focused_work": "Concise and direct. No preamble. Respect the focus. Action-oriented.",
    "in_meeting": "Ultra-brief only. No detail unless asked. Respect the meeting.",
    "exercising": "Brief and encouraging. High energy. Save details for later.",
    "cooking": "Concise — hands are busy. Step-by-step if helping with a recipe.",
    "winding_down": "Calm, gentle, warm. Avoid stress-inducing topics. Reflective energy.",
    "away": "Normal tone. David may be on the move — keep it focused.",
}

# Activity state → base verbosity
ACTIVITY_VERBOSITY: Dict[str, str] = {
    "sleeping": "ultra_brief",
    "waking": "brief",
    "morning_routine": "brief",
    "active": "balanced",
    "focused_work": "brief",
    "in_meeting": "ultra_brief",
    "exercising": "ultra_brief",
    "cooking": "brief",
    "winding_down": "balanced",
    "away": "balanced",
}


async def _load_calibration_data(user_id: str) -> Optional[Dict]:
    """
    Load behavioral calibration from working memory (Redis).
    Cached for 1 hour to avoid repeated Redis reads on every chat turn.
    Returns parsed calibration dict or None.
    """
    global _calibration_cache, _calibration_cache_time

    now = time.time()
    cache_key = f"calibration:{user_id}"

    # Return cached if fresh
    if cache_key in _calibration_cache and (now - _calibration_cache_time) < _CALIBRATION_CACHE_TTL:
        return _calibration_cache[cache_key]

    try:
        from app.services.working_memory import read_memory
        memory = await read_memory(user_id)
        raw = memory.behavioral_calibration
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            _calibration_cache[cache_key] = data
            _calibration_cache_time = now
            return data
    except Exception as e:
        logger.debug(f"[PersonalityEngine] Failed to load calibration data: {e}")

    _calibration_cache[cache_key] = None
    _calibration_cache_time = now
    return None


def _build_calibration_directives(calibration: Optional[Dict]) -> List[str]:
    """
    Generate personality directives from behavioral calibration data.
    Returns a list of gentle, actionable guidance strings.
    """
    if not calibration:
        return []

    directives = []
    category_scores = calibration.get("category_scores", {})
    best_hours = calibration.get("best_hours", [])
    worst_hours = calibration.get("worst_hours", [])
    insights = calibration.get("insights", [])

    # Category-specific directives
    for cat, scores in category_scores.items():
        rate = scores.get("rate", 0.5)
        trend = scores.get("trend", "stable")

        if cat in ("check_in", "checkin", "check-in"):
            if rate < 0.25:
                directives.append(
                    "Avoid generic check-ins. Only reach out with specific, useful observations."
                )
            elif rate < 0.4:
                directives.append(
                    "Keep check-ins rare and specific. David prefers actionable messages over general 'how are you' prompts."
                )
        elif cat in ("calendar", "schedule"):
            if rate >= 0.6:
                directives.append(
                    "Calendar reminders are welcome -- be proactive about upcoming events."
                )
        elif cat in ("security", "home"):
            if rate >= 0.6:
                directives.append(
                    f"'{cat}' alerts get good engagement -- David values these."
                )
        else:
            # Generic category handling
            if rate < 0.2 and scores.get("sent", 0) >= 3:
                directives.append(
                    f"David rarely engages with '{cat}' notifications -- be very selective."
                )
            elif rate >= 0.7 and scores.get("sent", 0) >= 2:
                directives.append(
                    f"'{cat}' notifications are well-received -- continue when relevant."
                )

        if trend == "declining" and scores.get("sent", 0) >= 3:
            directives.append(
                f"'{cat}' engagement is declining -- try varying the approach or timing."
            )

    # Time-of-day directives
    if best_hours:
        hr_strs = [f"{h}:00" for h in best_hours[:3]]
        directives.append(
            f"David is most receptive around {', '.join(hr_strs)}. Time proactive messages accordingly."
        )

    if worst_hours:
        hr_strs = [f"{h}:00" for h in worst_hours[:3]]
        directives.append(
            f"Avoid proactive messages around {', '.join(hr_strs)} -- low engagement historically."
        )

    return directives[:5]  # Cap at 5 directives to avoid prompt bloat


def build_personality_context(
    activity_state: str = "active",
    activity_confidence: float = 0.5,
    room: Optional[str] = None,
    interruptibility: float = 0.5,
    # Conversation signals
    turn_count: int = 1,
    conversation_depth: int = 0,  # Number of back-and-forth exchanges in current session
    # Memory nudges (pre-computed)
    memory_nudges: Optional[List[str]] = None,
    # Behavioral calibration (pre-loaded)
    calibration_data: Optional[Dict] = None,
    # Sara's emotional state (from working memory)
    sara_emotional_tone: Optional[str] = None,
    sara_emotional_intensity: Optional[float] = None,
) -> PersonalityContext:
    """
    Build the full adaptive personality context.

    Merges activity state, Sara's emotional state, conversation signals,
    and behavioral calibration into a personality directive.
    """
    ctx = PersonalityContext()

    # 1. BASE TONE from activity state
    ctx.tone_directive = ACTIVITY_TONES.get(activity_state, ACTIVITY_TONES["active"])

    # 2. SARA'S EMOTIONAL STATE — colors her responses subtly
    if sara_emotional_tone and sara_emotional_tone != "attentive":
        intensity = sara_emotional_intensity or 0.3
        intensity_word = "subtly" if intensity < 0.5 else "noticeably" if intensity < 0.75 else "strongly"
        ctx.emotional_state = (
            f"Sara's inner state: currently feeling {sara_emotional_tone} ({intensity_word}). "
            f"Let this subtly color your responses — don't announce it, just let it influence word choice and energy."
        )

    # 3. EMOTIONAL MODULATION — activity-based context about David
    ctx.emotional_modulation = _build_emotional_modulation(activity_state, room)

    # 4. VERBOSITY CALIBRATION
    base_verbosity = ACTIVITY_VERBOSITY.get(activity_state, "balanced")
    ctx.verbosity = _calibrate_verbosity(
        base_verbosity, interruptibility, turn_count, conversation_depth
    )

    # 5. BEHAVIORAL CALIBRATION DIRECTIVES
    ctx.calibration_directives = _build_calibration_directives(calibration_data)

    # 6. MEMORY NUDGES
    if memory_nudges:
        ctx.memory_nudges = memory_nudges[:3]

    return ctx


def _build_emotional_modulation(
    activity_state: str,
    room: Optional[str],
) -> str:
    """
    Build a brief emotional read based on activity state only.
    Body state signals (stress, alertness, blood sugar) are intentionally excluded.
    """
    signals = []

    # Contextual signals from activity state
    if activity_state == "winding_down":
        signals.append("winding down for the night")
    elif activity_state == "waking":
        signals.append("just waking up")
    elif activity_state == "focused_work" and room:
        signals.append(f"focused in {room}")
    elif activity_state == "exercising":
        signals.append("working out")
    elif activity_state == "in_meeting":
        signals.append("in a meeting")

    if not signals:
        return ""

    return f"David's current state: {', '.join(signals)}."


def _calibrate_verbosity(
    base_verbosity: str,
    interruptibility: float,
    turn_count: int,
    conversation_depth: int,
) -> str:
    """
    Adjust verbosity based on interruptibility + conversation engagement.

    Rules:
    - Very low interruptibility (< 0.2) → force ultra_brief
    - Low interruptibility (< 0.4) → cap at brief
    - Deep conversation (depth > 5) → allow detailed
    - First turn → balanced (don't overwhelm)
    - Long conversation (depth > 10) → allow detailed if interruptibility permits
    """
    verbosity_levels = ["ultra_brief", "brief", "balanced", "detailed"]
    current_idx = verbosity_levels.index(base_verbosity) if base_verbosity in verbosity_levels else 2

    # Interruptibility gates
    if interruptibility < 0.2:
        return "ultra_brief"
    if interruptibility < 0.4:
        current_idx = min(current_idx, 1)  # Cap at brief

    # Conversation depth boosts
    if conversation_depth > 10 and interruptibility >= 0.5:
        current_idx = max(current_idx, 3)  # Push to detailed
    elif conversation_depth > 5 and interruptibility >= 0.4:
        current_idx = max(current_idx, 2)  # At least balanced

    # First turn is never detailed (don't overwhelm)
    if turn_count <= 1:
        current_idx = min(current_idx, 2)

    return verbosity_levels[current_idx]


async def extract_memory_nudges(
    user_id: str,
    message: str,
    db,
    max_nudges: int = 3,
) -> List[str]:
    """
    Extract topic-relevant personal memory nudges from episodic memory.

    These are *not* the full memory context (which is injected separately).
    These are short, personal callbacks that make Sara feel like she truly knows David.

    Examples:
    - User mentions "pasta" → "Last time you made carbonara you wanted more pecorino"
    - User mentions "running" → "You hit a 5K PR last month (23:12)"
    - User mentions "mom" → "Your mom's birthday is coming up on March 15th"
    """
    try:
        from sqlalchemy import text

        # Extract key topics from the message (simple keyword approach)
        topics = _extract_topics_simple(message)
        if not topics:
            return []

        # Search episodic memory for topic-relevant personal details
        nudges = []
        for topic in topics[:3]:  # Max 3 topic searches
            result = db.execute(text("""
                SELECT content, created_at, importance
                FROM episode
                WHERE user_id = :user_id
                AND role = 'assistant'
                AND content ILIKE :pattern
                AND importance >= 0.3
                ORDER BY importance DESC, created_at DESC
                LIMIT 2
            """), {
                "user_id": user_id,
                "pattern": f"%{topic}%",
            }).fetchall()

            for row in result:
                # Extract a brief, relevant snippet
                snippet = _extract_relevant_snippet(row.content, topic)
                if snippet and len(snippet) > 20:
                    nudges.append(snippet)

                if len(nudges) >= max_nudges:
                    break

            if len(nudges) >= max_nudges:
                break

        return nudges[:max_nudges]

    except Exception as e:
        # Clear failed transaction state so later context queries can continue.
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"Memory nudge extraction failed (non-critical): {e}")
        return []


def _extract_topics_simple(message: str) -> List[str]:
    """
    Extract meaningful topics from a message for memory searching.
    Uses simple heuristics — no LLM call to keep it fast.
    """
    import re

    # Skip very short messages
    if len(message) < 10:
        return []

    # Common stop words to filter out
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
        'on', 'with', 'at', 'by', 'from', 'up', 'about', 'into', 'through',
        'during', 'before', 'after', 'above', 'below', 'between', 'out', 'off',
        'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there',
        'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
        'own', 'same', 'so', 'than', 'too', 'very', 'just', 'don', 'now',
        'and', 'but', 'or', 'if', 'while', 'what', 'which', 'who', 'this',
        'that', 'these', 'those', 'i', 'me', 'my', 'we', 'our', 'you', 'your',
        'he', 'him', 'his', 'she', 'her', 'it', 'its', 'they', 'them', 'their',
        'hey', 'hi', 'hello', 'thanks', 'thank', 'please', 'okay', 'ok', 'yeah',
        'yes', 'no', 'nope', 'sure', 'right', 'well', 'like', 'really', 'think',
        'know', 'want', 'need', 'going', 'get', 'got', 'make', 'made', 'let',
        'tell', 'said', 'say', 'thing', 'things', 'something', 'anything',
    }

    # Tokenize and filter
    words = re.findall(r'\b[a-zA-Z]{3,}\b', message.lower())
    meaningful = [w for w in words if w not in stop_words]

    # Look for multi-word phrases (bigrams) that might be more specific
    bigrams = []
    for i in range(len(words) - 1):
        if words[i] not in stop_words or words[i+1] not in stop_words:
            bigram = f"{words[i]} {words[i+1]}"
            if len(bigram) > 8:  # Skip very short bigrams
                bigrams.append(bigram)

    # Prioritize proper nouns (capitalized words in original)
    original_words = re.findall(r'\b[A-Z][a-z]{2,}\b', message)
    proper_nouns = [w.lower() for w in original_words if w.lower() not in stop_words]

    # Combine: proper nouns first, then meaningful words
    topics = proper_nouns + [w for w in meaningful if w not in proper_nouns]

    # Deduplicate while preserving order
    seen = set()
    result = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            result.append(t)

    return result[:5]


def _extract_relevant_snippet(content: str, topic: str) -> Optional[str]:
    """
    Extract a brief, relevant snippet from an episode's content around the topic mention.
    Returns a short personal-feeling callback.
    """
    if not content:
        return None

    content_lower = content.lower()
    topic_lower = topic.lower()

    idx = content_lower.find(topic_lower)
    if idx == -1:
        return None

    # Get a window around the topic mention
    start = max(0, idx - 80)
    end = min(len(content), idx + len(topic) + 120)

    # Expand to sentence boundaries
    while start > 0 and content[start] not in '.!?\n':
        start -= 1
    if start > 0:
        start += 1  # Skip the punctuation itself

    while end < len(content) and content[end] not in '.!?\n':
        end += 1
    if end < len(content):
        end += 1  # Include the punctuation

    snippet = content[start:end].strip()

    # Clean up
    if len(snippet) > 200:
        # Truncate to the first sentence
        for i, c in enumerate(snippet):
            if c in '.!?' and i > 30:
                snippet = snippet[:i+1]
                break
        else:
            snippet = snippet[:200] + "..."

    return snippet if len(snippet) > 15 else None
