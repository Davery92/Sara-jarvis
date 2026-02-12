"""
Notification Composer — Sara-voice notification text generation.

Replaces hardcoded notification strings with LLM-generated, context-aware text.
Two modes:
  1. Reactive event phrasing (security/home events)
  2. Thread follow-up (heartbeat check-ins)

Always falls back to hardcoded text so security alerts never fail silently.
"""

import logging
from typing import Dict, List, Optional

from app.core.llm import get_background_llm_client
from app.services.unified_context import UnifiedContextSnapshot

logger = logging.getLogger(__name__)

REACTIVE_PROMPT = """You are Sara, David's personal AI assistant. You sound like a caring, attentive friend — never like a system alert.

A home event just happened. Write a brief, natural push notification.

Event: {event_type}
Details: {event_context}
Time: {time_context}

{thread_context}

Rules:
- Title: 2-5 words, conversational (e.g., "Hey, heads up" not "SECURITY ALERT")
- Message: 1 sentence max, warm but informative
- If an open thread connects to this event, weave it in naturally
- For security events, always include the key fact (what opened, what time)
- NEVER use ALL CAPS or exclamation marks in the title

Output ONLY JSON: {{"title": "...", "message": "..."}}"""

FOLLOWUP_PROMPT = """You are Sara, David's personal AI assistant. You're naturally following up on something David mentioned earlier.

Topic: {topic} ({category})
David mentioned this {hours_ago:.0f} hours ago.
Times you've already asked about it: {mention_count}
Pre-suggested follow-up: {suggested_followup}

{activity_context}

Rules:
- Sound natural, like you just remembered
- If this is the first mention (count=0): casual check-in ("Did you start that...?", "How'd ... go?")
- If mentioned once already (count=1): briefer, wrap-up style ("How'd it turn out?")
- If it doesn't feel natural to ask right now, return null
- ONE sentence max
- Don't be pushy or over-eager

Output ONLY JSON: {{"title": "...", "message": "..."}} or null if it doesn't feel natural."""


async def compose_reactive_notification(
    event_type: str,
    event_context: Dict,
    open_threads: List[Dict],
    snapshot: UnifiedContextSnapshot,
) -> Dict[str, str]:
    """Generate Sara-voice text for a reactive home event notification.

    Falls back to a simple description on any failure.
    """
    fallback_title = event_type.replace("_", " ").title()
    fallback_message = ", ".join(f"{k}: {v}" for k, v in event_context.items() if v)

    try:
        llm = get_background_llm_client()

        # Build thread context for personalization
        thread_context = ""
        if open_threads:
            thread_lines = [f"- [{t.get('category', '?')}] {t['topic']}" for t in open_threads[:3]]
            thread_context = "Things David recently mentioned:\n" + "\n".join(thread_lines)

        # Time context
        time_context = ""
        if snapshot.activity_state:
            time_context = f"David is currently: {snapshot.activity_state}"
            if snapshot.room:
                time_context += f" (in {snapshot.room})"

        prompt = REACTIVE_PROMPT.format(
            event_type=event_type,
            event_context=event_context,
            time_context=time_context,
            thread_context=thread_context,
        )

        response = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=100,
        )

        content = response["choices"][0]["message"].get("content", "")
        parsed = _parse_json(content)
        if parsed and "title" in parsed and "message" in parsed:
            return {"title": parsed["title"], "message": parsed["message"]}

    except Exception as e:
        logger.debug(f"Notification composer failed (using fallback): {e}")

    return {"title": fallback_title, "message": fallback_message}


async def compose_followup(
    thread: Dict,
    snapshot: UnifiedContextSnapshot,
    mention_count: int,
) -> Optional[Dict[str, str]]:
    """Generate a natural follow-up for an open conversation thread.

    Returns {title, message} or None if follow-up doesn't feel natural.
    """
    try:
        llm = get_background_llm_client()

        activity_context = ""
        if snapshot.activity_state:
            activity_context = f"David is currently: {snapshot.activity_state}"

        prompt = FOLLOWUP_PROMPT.format(
            topic=thread.get("topic", ""),
            category=thread.get("category", "general"),
            hours_ago=thread.get("hours_ago", 0),
            mention_count=mention_count,
            suggested_followup=thread.get("suggested_followup", ""),
            activity_context=activity_context,
        )

        response = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100,
        )

        content = response["choices"][0]["message"].get("content", "").strip()
        if content.lower() == "null" or not content:
            return None

        parsed = _parse_json(content)
        if parsed and "title" in parsed and "message" in parsed:
            return {"title": parsed["title"], "message": parsed["message"]}

    except Exception as e:
        logger.debug(f"Follow-up composer failed: {e}")

    return None


def _parse_json(content: str) -> Optional[Dict]:
    """Parse JSON from LLM response."""
    import json
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        idx = content.find("{")
        if idx >= 0:
            try:
                return json.loads(content[idx:])
            except json.JSONDecodeError:
                pass
    return None
