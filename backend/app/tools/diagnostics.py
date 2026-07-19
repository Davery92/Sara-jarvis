"""Read-only self-diagnostics tools — "Sara, what's wrong?"

These let both the Claude chat persona and Qwen agents query Sara's own health:
failing tasks, error events, and a full explanation of any single event, plus a
handoff report for David → Claude Code. HARD POLICY: read-only. Sara can read
everything about herself and modify nothing — no writes here except the optional
handoff *note* (her own journal-style output), never her code or config.
"""
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult
from app.services import diagnostics_service as diag


class DiagnosticsOverviewTool(BaseTool):
    @property
    def name(self) -> str:
        return "diagnostics_overview"

    @property
    def description(self) -> str:
        return ("Get a one-call summary of Sara's own health: failing background tasks, "
                "error counts by service (last 24h), queue depths, and daemon heartbeat. "
                "Use when David asks 'what's broken?', 'are you okay?', 'is anything failing?'.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        ov = await diag.diagnostics_overview()
        n = ov["failing_task_count"]
        if n == 0:
            msg = "Everything's healthy — no failing tasks in the last 24h."
        else:
            names = ", ".join(f["task_name"].split(".")[-1] for f in ov["failing_tasks"][:5])
            msg = f"{n} task(s) failing in the last 24h: {names}."
        return ToolResult(success=True, data=ov, message=msg)


class DiagnosticsFailuresTool(BaseTool):
    @property
    def name(self) -> str:
        return "diagnostics_failures"

    @property
    def description(self) -> str:
        return ("List Sara's failing background tasks with counts and sample errors. "
                "Optionally filter by task_name and time window.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Optional substring filter on task name"},
                "since_hours": {"type": "integer", "description": "Look-back window in hours (default 24)"},
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        hours = int(kwargs.get("since_hours") or 24)
        task_filter = (kwargs.get("task_name") or "").strip().lower()
        failing = await diag.get_failing_tasks(hours=hours)
        if task_filter:
            failing = [f for f in failing if task_filter in f["task_name"].lower()]
        if not failing:
            return ToolResult(success=True, data=[], message="No failing tasks match.")
        return ToolResult(success=True, data=failing,
                          message=f"{len(failing)} failing task(s).")


class DiagnosticsEventsTool(BaseTool):
    @property
    def name(self) -> str:
        return "diagnostics_events"

    @property
    def description(self) -> str:
        return ("Search Sara's internal system_event log (WARNING+ records, task failures, "
                "deploy/health events) by service, level, time window, or text query.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Filter by service/logger name (substring)"},
                "level": {"type": "string", "description": "WARNING, ERROR, or CRITICAL"},
                "since_hours": {"type": "integer", "description": "Look-back window in hours (default 24)"},
                "query": {"type": "string", "description": "Text to match in the message"},
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        events = await diag.search_events(
            service=kwargs.get("service"), level=kwargs.get("level"),
            since_hours=int(kwargs.get("since_hours") or 24),
            query=kwargs.get("query"), limit=50)
        return ToolResult(success=True, data=events, message=f"{len(events)} event(s).")


class DiagnosticsExplainTool(BaseTool):
    @property
    def name(self) -> str:
        return "diagnostics_explain"

    @property
    def description(self) -> str:
        return ("Explain one diagnostics event in full: first/last seen, occurrence count, "
                "traceback, and which user-facing feature it breaks. Pass the event_id from "
                "an overview/failures/events result or a health notification.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"event_id": {"type": "string", "description": "The event_id to explain"}},
            "required": ["event_id"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        event_id = (kwargs.get("event_id") or "").strip()
        if not event_id:
            return ToolResult(success=False, message="event_id is required.")
        detail = await diag.explain_event(event_id)
        if not detail:
            return ToolResult(success=False, message=f"No event found for {event_id}.")
        feat = detail.get("breaks_feature")
        msg = f"{detail.get('error_class') or detail.get('kind')}"
        if feat:
            msg += f" — breaks {feat}"
        return ToolResult(success=True, data=detail, message=msg)


class DiagnosticsReportTool(BaseTool):
    @property
    def name(self) -> str:
        return "diagnostics_report"

    @property
    def description(self) -> str:
        return ("Compile a markdown handoff bundle about a problem (symptoms, timeline, error "
                "counts, sample tracebacks, suspected features) for David to hand to Claude Code. "
                "Saves it as a note and returns the markdown. This is the sanctioned bridge to a "
                "real fix: Sara diagnoses and writes it up; a human + Claude Code changes the code.")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "What the report is about"}},
            "required": ["topic"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        topic = (kwargs.get("topic") or "system health").strip()
        report = await diag.build_report(topic)
        note_id = None
        try:
            note_id = await _save_report_note(user_id, topic, report)
        except Exception:
            note_id = None
        return ToolResult(success=True, data={"markdown": report, "note_id": note_id},
                          message=f"Diagnostics report for '{topic}' compiled"
                                  + (f" and saved as note {note_id}." if note_id else "."))


async def _save_report_note(user_id: str, topic: str, markdown: str):
    """Best-effort: persist the handoff bundle as a note the user can open."""
    import uuid
    from app.core.timezone import naive_utc_now
    from app.db.session import get_async_session_factory
    from sqlalchemy import text
    factory = get_async_session_factory()
    nid = str(uuid.uuid4())
    async with factory() as db:
        # Detect whether note table has a naive or aware created_at; use naive UTC
        # (note table predates the timestamptz convention).
        await db.execute(text("""
            INSERT INTO note (id, user_id, title, content, created_at, updated_at)
            VALUES (:id, :uid, :title, :content, :now, :now)
        """), {"id": nid, "uid": user_id,
               "title": f"Diagnostics: {topic}", "content": markdown,
               "now": naive_utc_now()})
        await db.commit()
    return nid


DIAGNOSTICS_TOOLS = [
    DiagnosticsOverviewTool(),
    DiagnosticsFailuresTool(),
    DiagnosticsEventsTool(),
    DiagnosticsExplainTool(),
    DiagnosticsReportTool(),
]
