"""
Action Suggester

Generates contextual suggested actions based on the last tools used,
response type, and context state. These appear as tappable chips below
Sara's response in the iOS app.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# Tool-specific follow-up suggestions
TOOL_SUGGESTIONS: Dict[str, List[Dict[str, Any]]] = {
    "calendar_list": [
        {"label": "Add event", "message": "Add a new calendar event"},
        {"label": "Tomorrow", "message": "What's on my calendar tomorrow?"},
    ],
    "list_events": [
        {"label": "Add event", "message": "Add a new calendar event"},
        {"label": "Tomorrow", "message": "What's on tomorrow?"},
    ],
    "calendar_create": [
        {"label": "My schedule", "message": "Show my schedule for today"},
    ],
    "create_event": [
        {"label": "My schedule", "message": "Show me today's schedule"},
    ],
    "log_food": [
        {"label": "Nutrition summary", "message": "How's my nutrition today?"},
        {"label": "Log another meal", "message": "I want to log another meal"},
    ],
    "food_log_search": [
        {"label": "Nutrition summary", "message": "Give me my nutrition summary"},
    ],
    "food_log_summary": [
        {"label": "Log a meal", "message": "I want to log a meal"},
    ],
    "nutrition_summary": [
        {"label": "Log a meal", "message": "I want to log a meal"},
    ],
    "notes_search": [
        {"label": "Create note", "message": "Create a new note"},
        {"label": "Search again", "message": "Search my notes for "},
    ],
    "notes_list": [
        {"label": "Create note", "message": "Create a new note"},
        {"label": "View Notes", "action": "navigate", "target": "Notes"},
    ],
    "notes_create": [
        {"label": "View Notes", "action": "navigate", "target": "Notes"},
    ],
    "reminders_list": [
        {"label": "Add reminder", "message": "Set a reminder for "},
    ],
    "reminders_create": [
        {"label": "My reminders", "message": "Show my reminders"},
    ],
    "timers_start": [
        {"label": "Cancel timer", "message": "Cancel my timer"},
    ],
    "timers_status": [
        {"label": "Start timer", "message": "Start a timer for "},
    ],
    "get_weather": [
        {"label": "Tomorrow?", "message": "What's the weather tomorrow?"},
        {"label": "This weekend?", "message": "What's the weather this weekend?"},
    ],
    "weather": [
        {"label": "Tomorrow?", "message": "What's the weather tomorrow?"},
    ],
    "home_status": [
        {"label": "All lights off", "message": "Turn off all the lights"},
    ],
    "get_home_status": [
        {"label": "All lights off", "message": "Turn off all the lights"},
    ],
    "email_search": [
        {"label": "Recent emails", "message": "Show my recent emails"},
    ],
    "email_recent": [
        {"label": "Search email", "message": "Search my email for "},
    ],
    "search_email": [
        {"label": "Recent emails", "message": "Show me recent emails"},
    ],
    "health_status": [
        {"label": "View Health", "action": "navigate", "target": "Health"},
    ],
    "health_trend": [
        {"label": "View Health", "action": "navigate", "target": "Health"},
    ],
    "learning_topic_list": [
        {"label": "Continue Learning", "action": "navigate", "target": "Learning"},
    ],
    "create_research_plan": [
        {"label": "Check status", "message": "What's the status of my research?"},
    ],
}


def suggest(
    tool_history: List[str],
    response_content: str,
    unified_context: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    Generate contextual action suggestions.

    Args:
        tool_history: List of tool names used in this turn
        response_content: Sara's final response text
        unified_context: Optional unified context dict

    Returns:
        List of suggestion dicts with label, message/action/target
    """
    suggestions: List[Dict[str, Any]] = []
    seen_labels: set = set()

    # 1. Tool-specific suggestions (most relevant)
    for tool_name in reversed(tool_history):  # Most recent tool first
        tool_suggestions = TOOL_SUGGESTIONS.get(tool_name, [])
        for s in tool_suggestions:
            if s["label"] not in seen_labels:
                suggestions.append(s)
                seen_labels.add(s["label"])

    # 2. Response-type suggestions: intentionally none.
    #
    # There used to be length-triggered "Summarize" (>500 chars) and "Tell me
    # more" (>200 chars) fallbacks here, which fired on almost every plain
    # answer — so nearly every turn came back with a suggestion row whether or
    # not there was anything worth suggesting, and on iOS that row was a
    # ~150pt card. A suggestion should come from something Sara actually did
    # (a tool) or from real context below, never from her having typed a few
    # sentences. Removed 2026-08-25.

    # 3. Context-aware suggestions
    if unified_context and isinstance(unified_context, dict):
        # If calories are low, suggest logging food
        calories = unified_context.get("calories_today", 0)
        calorie_goal = unified_context.get("calorie_goal", 0)
        if calorie_goal and calories < calorie_goal * 0.4 and "Log a meal" not in seen_labels:
            suggestions.append({"label": "Log a meal", "message": "I want to log a meal"})
            seen_labels.add("Log a meal")

        # If there are open threads
        open_threads = unified_context.get("open_thread_count", 0)
        if open_threads > 0 and "Open threads" not in seen_labels:
            topics = unified_context.get("ripe_thread_topics", [])
            if topics:
                suggestions.append({
                    "label": f"Follow up: {topics[0][:20]}",
                    "message": f"Let's follow up on {topics[0]}",
                })

        # Learning reviews due — disabled

    # Cap at 3 — this renders as a single chip row on iOS, and a fourth chip
    # is off-screen more often than not.
    return suggestions[:3]
