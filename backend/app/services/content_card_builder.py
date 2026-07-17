"""
Content Card Builder

Transforms tool results into standardized card payloads for rich rendering
in the iOS app. Each card type has a builder function that extracts the
relevant data from tool results.
"""

import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Map tool names to card types
TOOL_TO_CARD_TYPE: Dict[str, str] = {
    # Calendar
    "calendar_list": "calendar_card",
    "list_events": "calendar_card",
    "calendar_create": "calendar_card",
    "create_event": "calendar_card",
    # Reminders
    "list_reminders": "reminder_card",
    "create_reminder": "reminder_card",
    # Timers
    "start_timer": "timer_card",
    "list_timers": "timer_card",
    # Notes
    "search_notes": "notes_card",
    "list_notes": "notes_card",
    # Weather
    "get_weather": "weather_card",
    "weather": "weather_card",
    # Nutrition
    "log_food": "nutrition_card",
    "food_log_search": "nutrition_card",
    "food_log_summary": "nutrition_card",
    "nutrition_summary": "nutrition_card",
    # Email
    "email_search": "email_card",
    "email_recent": "email_card",
    "search_email": "email_card",
    # Health
    "health_status": "health_card",
    "health_trend": "health_card",
    # Learning
    "learning_topic_list": "learning_card",
    "list_learning_topics": "learning_card",
    # Inbox
    "inbox_search": "inbox_card",
    "inbox_list": "inbox_card",
    # Home
    "home_status": "home_card",
    "get_home_status": "home_card",
    "list_home_devices": "home_card",
}


def build_card(tool_name: str, tool_result: str) -> Optional[Dict[str, Any]]:
    """
    Build a content card from a tool result.

    Returns None if the tool doesn't map to a card type or the result
    has no meaningful data.
    """
    card_type = TOOL_TO_CARD_TYPE.get(tool_name)
    if not card_type:
        return None

    try:
        # Parse tool result
        if isinstance(tool_result, str):
            result_data = json.loads(tool_result)
        else:
            result_data = tool_result

        # Skip failed tool calls
        if isinstance(result_data, dict) and result_data.get("success") is False:
            return None

        builder = CARD_BUILDERS.get(card_type)
        if not builder:
            return None

        card_data = builder(tool_name, result_data)
        if card_data is None:
            return None

        return {
            "card_type": card_type,
            **card_data,
        }
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Card build failed for {tool_name}: {e}")
        return None


def _build_calendar_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a calendar card from event data."""
    events = []
    if isinstance(data, dict):
        events = data.get("data", data.get("events", []))
        if isinstance(events, dict):
            events = events.get("events", [])
    elif isinstance(data, list):
        events = data

    if not events and "create" not in tool_name:
        return None

    items = []
    for ev in (events if isinstance(events, list) else [])[:8]:
        if isinstance(ev, dict):
            items.append({
                "id": ev.get("id"),
                "title": ev.get("title", ev.get("summary", "")),
                "start_time": ev.get("start_time", ev.get("start", "")),
                "end_time": ev.get("end_time", ev.get("end", "")),
                "location": ev.get("location"),
                "all_day": ev.get("all_day", False),
            })

    return {
        "title": "Today's Events" if "list" in tool_name else "Calendar",
        "items": items,
        "summary": f"{len(items)} event{'s' if len(items) != 1 else ''}",
        "actions": [
            {"label": "Add Event", "action": "navigate", "target": "EventForm"},
            {"label": "View All", "action": "navigate", "target": "Calendar"},
        ],
    }


def _build_reminder_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a reminder card."""
    reminders = []
    if isinstance(data, dict):
        reminders = data.get("data", data.get("reminders", []))
        if isinstance(reminders, dict):
            reminders = reminders.get("reminders", [])
    elif isinstance(data, list):
        reminders = data

    if not reminders and "create" not in tool_name:
        return None

    items = []
    for r in (reminders if isinstance(reminders, list) else [])[:8]:
        if isinstance(r, dict):
            items.append({
                "id": r.get("id"),
                "title": r.get("title", ""),
                "due_at": r.get("due_at", r.get("reminder_time", "")),
                "completed": r.get("completed", False),
            })

    return {
        "title": "Reminders",
        "items": items,
        "summary": f"{len(items)} reminder{'s' if len(items) != 1 else ''}",
        "actions": [
            {"label": "Add Reminder", "action": "navigate", "target": "ReminderForm"},
        ],
    }


def _build_timer_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a timer card."""
    timer_data = data if isinstance(data, dict) else {}
    inner = timer_data.get("data", timer_data)
    if isinstance(inner, dict) and inner.get("timer_id"):
        return {
            "title": inner.get("title", "Timer"),
            "items": [{
                "id": inner.get("timer_id"),
                "title": inner.get("title", "Timer"),
                "duration_seconds": inner.get("duration_seconds", 0),
                "remaining_seconds": inner.get("remaining_seconds", inner.get("duration_seconds", 0)),
            }],
            "actions": [
                {"label": "Cancel", "action": "message", "message": "Cancel my timer"},
            ],
        }

    # List of timers
    timers = inner if isinstance(inner, list) else inner.get("timers", [])
    if not timers:
        return None

    items = []
    for t in (timers if isinstance(timers, list) else [])[:5]:
        if isinstance(t, dict):
            items.append({
                "id": t.get("id", t.get("timer_id")),
                "title": t.get("title", t.get("name", "")),
                "duration_seconds": t.get("duration_seconds", 0),
                "remaining_seconds": t.get("remaining_seconds", 0),
            })

    return {
        "title": "Timers",
        "items": items,
        "actions": [],
    }


def _build_notes_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a notes card."""
    notes = []
    if isinstance(data, dict):
        notes = data.get("data", data.get("notes", data.get("results", [])))
        if isinstance(notes, dict):
            notes = notes.get("notes", notes.get("results", []))
    elif isinstance(data, list):
        notes = data
    elif isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                notes = parsed
            elif isinstance(parsed, dict):
                notes = parsed.get("notes", parsed.get("results", []))
        except Exception:
            return None

    if not notes:
        return None

    items = []
    for n in (notes if isinstance(notes, list) else [])[:6]:
        if isinstance(n, dict):
            content = n.get("content", "")
            items.append({
                "id": n.get("id"),
                "title": n.get("title", "Untitled"),
                "preview": content[:120] if content else "",
                "folder": n.get("folder_name", n.get("folder")),
                "updated_at": n.get("updated_at"),
            })

    # Single result → detail card
    if len(items) == 1:
        return {
            "card_type": "note_detail_card",
            "title": items[0]["title"],
            "items": items,
            "actions": [
                {"label": "Edit", "action": "navigate", "target": "NoteEditor", "params": {"noteId": items[0]["id"]}},
            ],
        }

    return {
        "title": "Notes",
        "items": items,
        "summary": f"{len(items)} note{'s' if len(items) != 1 else ''} found",
        "actions": [
            {"label": "View All", "action": "navigate", "target": "Notes"},
        ],
    }


def _build_weather_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a weather card."""
    weather = data if isinstance(data, dict) else {}
    inner = weather.get("data", weather)
    if not inner or not isinstance(inner, dict):
        return None

    return {
        "title": "Weather",
        "items": [{
            "temp": inner.get("temperature", inner.get("temp")),
            "conditions": inner.get("conditions", inner.get("description", "")),
            "humidity": inner.get("humidity"),
            "wind": inner.get("wind_speed", inner.get("wind")),
            "forecast": inner.get("forecast", []),
        }],
        "actions": [
            {"label": "Tomorrow?", "action": "message", "message": "What's the weather tomorrow?"},
        ],
    }


def _build_nutrition_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a nutrition card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    if not inner:
        return None

    items = []
    if isinstance(inner, dict):
        meals = inner.get("meals", inner.get("food_logs", []))
        if isinstance(meals, list):
            for m in meals[:6]:
                if isinstance(m, dict):
                    items.append({
                        "meal_type": m.get("meal_type", ""),
                        "description": m.get("description", m.get("items_text", "")),
                        "calories": m.get("calories", 0),
                        "logged_at": m.get("logged_at", ""),
                    })

        summary_data = {
            "calories": inner.get("total_calories", inner.get("calories", 0)),
            "protein": inner.get("total_protein", inner.get("protein", 0)),
            "carbs": inner.get("total_carbs", inner.get("carbs", 0)),
            "fats": inner.get("total_fats", inner.get("fats", 0)),
        }
    else:
        summary_data = {}

    return {
        "title": "Nutrition",
        "items": items,
        "summary_data": summary_data,
        "actions": [
            {"label": "Log Meal", "action": "message", "message": "I want to log a meal"},
        ],
    }


def _build_email_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build an email card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    emails = inner if isinstance(inner, list) else (inner.get("emails", []) if isinstance(inner, dict) else [])

    if not emails:
        return None

    items = []
    for e in (emails if isinstance(emails, list) else [])[:5]:
        if isinstance(e, dict):
            items.append({
                "id": e.get("id"),
                "sender": e.get("sender", e.get("from", "")),
                "subject": e.get("subject", ""),
                "snippet": e.get("snippet", e.get("preview", ""))[:100],
                "timestamp": e.get("received_at", e.get("date", "")),
                "is_read": e.get("is_read", True),
            })

    return {
        "title": "Email",
        "items": items,
        "summary": f"{len(items)} email{'s' if len(items) != 1 else ''}",
        "actions": [],
    }


def _build_health_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a health card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    if not inner or not isinstance(inner, dict):
        return None

    metrics = inner.get("metrics", inner)
    items = []
    for key, value in (metrics.items() if isinstance(metrics, dict) else []):
        if isinstance(value, (int, float, str)):
            items.append({"metric": key, "value": value})

    if not items:
        return None

    return {
        "title": "Health Metrics",
        "items": items[:8],
        "actions": [
            {"label": "View All", "action": "navigate", "target": "Health"},
        ],
    }


def _build_learning_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a learning card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    topics = inner if isinstance(inner, list) else (inner.get("topics", []) if isinstance(inner, dict) else [])

    if not topics:
        return None

    items = []
    for t in (topics if isinstance(topics, list) else [])[:6]:
        if isinstance(t, dict):
            items.append({
                "id": t.get("id"),
                "name": t.get("name", t.get("topic", "")),
                "mastery": t.get("mastery", t.get("mastery_level", 0)),
                "status": t.get("status", "active"),
            })

    return {
        "title": "Learning Topics",
        "items": items,
        "actions": [
            {"label": "Continue Learning", "action": "navigate", "target": "Learning"},
        ],
    }


def _build_inbox_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build an inbox card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    inbox_items = inner if isinstance(inner, list) else (inner.get("items", []) if isinstance(inner, dict) else [])

    if not inbox_items:
        return None

    items = []
    for item in (inbox_items if isinstance(inbox_items, list) else [])[:5]:
        if isinstance(item, dict):
            items.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "source": item.get("source", item.get("domain", "")),
                "status": item.get("status", "unread"),
            })

    return {
        "title": "Inbox",
        "items": items,
        "actions": [
            {"label": "View All", "action": "navigate", "target": "Inbox"},
        ],
    }


def _build_home_card(tool_name: str, data: Any) -> Optional[Dict]:
    """Build a home card."""
    inner = data.get("data", data) if isinstance(data, dict) else data
    if not inner or not isinstance(inner, dict):
        return None

    devices = inner.get("devices", inner.get("entities", []))
    items = []
    for d in (devices if isinstance(devices, list) else [])[:8]:
        if isinstance(d, dict):
            items.append({
                "id": d.get("entity_id", d.get("id", "")),
                "name": d.get("friendly_name", d.get("name", "")),
                "state": d.get("state", "unknown"),
                "domain": d.get("domain", ""),
            })

    if not items:
        return None

    return {
        "title": "Home",
        "items": items,
        "actions": [
            {"label": "All Lights Off", "action": "message", "message": "Turn off all the lights"},
        ],
    }


# Map card types to builder functions
CARD_BUILDERS: Dict[str, Any] = {
    "calendar_card": _build_calendar_card,
    "reminder_card": _build_reminder_card,
    "timer_card": _build_timer_card,
    "notes_card": _build_notes_card,
    "note_detail_card": _build_notes_card,
    "weather_card": _build_weather_card,
    "nutrition_card": _build_nutrition_card,
    "email_card": _build_email_card,
    "health_card": _build_health_card,
    "learning_card": _build_learning_card,
    "inbox_card": _build_inbox_card,
    "home_card": _build_home_card,
}
