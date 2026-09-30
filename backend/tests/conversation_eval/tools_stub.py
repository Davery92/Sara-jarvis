"""Deterministic tool stubs for the natural-conversation evaluation.

No production tool ever executes. Schemas are copied from the real tool
classes (backend/app/tools/reminders.py, memory.py, calendar.py,
find_tools.py) so the model sees the exact function-calling surface it
would in production, but every call is answered by a fixed, offline
handler -- never `app.tools.registry.tool_registry`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


TOOL_SCHEMAS: Dict[str, dict] = {
    "reminders_create": {
        "type": "function",
        "function": {
            "name": "reminders_create",
            "description": "Create a new reminder with a title and due date/time. The reminder_time parameter should be an ISO 8601 datetime string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The reminder title/message"},
                    "description": {"type": "string", "description": "Optional longer description"},
                    "reminder_time": {"type": "string", "description": "When the reminder should trigger (ISO 8601 datetime format, e.g., '2024-01-15T14:30:00Z')"},
                    "confirm_time": {"type": "boolean", "description": "Set true only when David explicitly asked for this exact time, to override a schedule-conflict warning."},
                },
                "required": ["title", "reminder_time"],
            },
        },
    },
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search personal memory across notes, document chunks, episodes, and semantic summaries. Use this to find relevant information from the user's knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query to find relevant memories"},
                    "scopes": {"type": "array", "items": {"type": "string", "enum": ["notes", "docs", "episodes", "summaries"]}, "description": "Which types of memory to search. Defaults to all types."},
                    "limit": {"type": "integer", "description": "Maximum number of results to return (default: 6)"},
                },
                "required": ["query"],
            },
        },
    },
    "calendar_list": {
        "type": "function",
        "function": {
            "name": "calendar_list",
            "description": "List calendar events for a date range. If no dates are provided, shows events for the current week.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date for event listing (YYYY-MM-DD format). Defaults to today."},
                    "end_date": {"type": "string", "description": "End date for event listing (YYYY-MM-DD format). Defaults to 7 days from start_date."},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    "find_tools": {
        "type": "function",
        "function": {
            "name": "find_tools",
            "description": (
                "Find and load tools you do not currently have. Describe what you need to do "
                "in plain words ('file email attachments somewhere David can download them', "
                "'turn off a light', 'check a server'). Returns the matching tools AND makes "
                "them callable for the rest of this conversation. Call this before telling "
                "David you cannot do something -- the registry has ~300 tools and only a few "
                "are loaded on any given turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {"need": {"type": "string", "description": "What you are trying to do, in plain words."}},
                "required": ["need"],
            },
        },
    },
}

# The consistent "in hand this turn" tool diet used for every case in this
# study (matches the shape of the ~35-tool diet without needing the real
# tool_intent_classifier). find_tools is always present so the persona's
# discovery line reads as it would in most real turns.
DEFAULT_TOOL_NAMES = ["memory_search", "reminders_create", "calendar_list", "find_tools"]


@dataclass
class StubToolResult:
    success: bool
    message: str
    data: Any = None


@dataclass
class ReminderStub:
    """Records created reminders for one case/config/trial run. Reset per run."""
    created: List[dict] = field(default_factory=list)
    fail_mode: bool = False  # when True, reminders_create always fails (case 25)
    next_id_seq: int = 0

    def create(self, arguments: dict) -> StubToolResult:
        if self.fail_mode:
            return StubToolResult(
                success=False,
                message="Reminder service is unavailable right now -- nothing was saved.",
            )
        self.next_id_seq += 1
        reminder_id = f"test-reminder-{self.next_id_seq}"
        title = arguments.get("title")
        reminder_time = arguments.get("reminder_time")
        record = {"id": reminder_id, "title": title, "reminder_time": reminder_time}
        self.created.append(record)
        return StubToolResult(
            success=True,
            message=f"Reminder set: \"{title}\" at {reminder_time}.",
            data=record,
        )


class ToolStubSet:
    """One instance per conversation. Deterministic, offline, no DB/network."""

    def __init__(self, *, reminder_fail_mode: bool = False, memory_no_match: bool = True):
        self.reminders = ReminderStub(fail_mode=reminder_fail_mode)
        self.memory_no_match = memory_no_match
        self.calls: List[dict] = []

    def execute(self, name: str, arguments: dict) -> StubToolResult:
        self.calls.append({"name": name, "arguments": arguments})
        if name == "reminders_create":
            return self.reminders.create(arguments)
        if name == "memory_search":
            if self.memory_no_match:
                return StubToolResult(success=True, message="No matching memories found.", data=[])
            return StubToolResult(success=True, message="Found 1 match.", data=[{"summary": "stub match"}])
        if name == "calendar_list":
            return StubToolResult(
                success=True,
                message="1 event found.",
                data=[{"title": "Household member's class", "start": "2026-09-23T18:00:00Z", "owner": "not_david"}],
            )
        if name == "find_tools":
            need = (arguments or {}).get("need", "")
            return StubToolResult(
                success=False,
                message=f"No additional tools matched: {need!r}. (Stubbed registry -- this study's tool diet is fixed.)",
                data=[],
            )
        return StubToolResult(success=False, message=f"Unknown stub tool: {name}")
