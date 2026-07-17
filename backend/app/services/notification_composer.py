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


GENERIC_REPHRASE_PROMPT = """You are Sara, David's personal AI assistant. Rewrite this notification so it \
sounds like you said it out loud to a friend — never like a system log line or an email client's raw fields.

Original title: {title}
Original message: {message}
Category: {category}

Rules:
- Keep every concrete fact from the original: names, subjects, numbers, times — never invent, drop, or soften them
- One sentence for the message, warm and direct, in first person where natural
- Title: 2-6 words, conversational
- NEVER use ALL CAPS, raw field labels ("From:", "RE:", "New Internal Email"), or ticket-speak
- If the original is already natural, warm, and one sentence, return it unchanged

Output ONLY JSON: {{"title": "...", "message": "..."}}"""

# Categories exempted from the phrasing stage: raw timer/reminder fires are
# meant to read as plain system fact ("Timer done"), not a composed line —
# SARA_UNLEASHED Phase T.1's invariant 6 exemption.
_PHRASING_EXEMPT_CATEGORIES = {"timer", "timer_complete", "reminder"}


async def compose_notification_text(
    title: str,
    message: str,
    category: str,
    source: str = "",
) -> Dict[str, str]:
    """Generic phrasing-stage pass (SARA_UNLEASHED Phase T.1): the mandatory
    final stage before any notification is sent, for every category except
    raw timer/reminder fires. Everything David reads from Sara passes
    through here so email alerts, deliberation proposals, and task
    completions all sound like the same voice instead of three different
    registers (Sara-voice composer, raw system alert, leaked agent
    monologue).

    Always falls back to the original (title, message) on any failure —
    a phrasing hiccup must never block or blank out a real notification,
    especially a security alert."""
    if category in _PHRASING_EXEMPT_CATEGORIES:
        return {"title": title, "message": message}

    try:
        from app.services.tunables import get_tunable_bool
        if not get_tunable_bool("notify.compose_all", True):
            return {"title": title, "message": message}
    except Exception:
        pass

    fallback = {"title": title, "message": message}
    try:
        llm = get_background_llm_client()
        prompt = GENERIC_REPHRASE_PROMPT.format(
            title=title, message=message, category=category or "general",
        )
        response = await llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=150,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        content = response["choices"][0]["message"].get("content", "")
        parsed = _parse_json(content)
        if parsed and parsed.get("title") and parsed.get("message"):
            return {"title": str(parsed["title"])[:200], "message": str(parsed["message"])[:1000]}
    except Exception as e:
        logger.debug(f"Notification phrasing stage failed (using original text): {e}")

    return fallback


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
