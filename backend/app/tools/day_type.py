"""set_day_type chat tool (Phase 10D) — flip today (or a date) to rest/training.

The one new action the office/rest-day scenario hinges on: when David isn't at
the office and skips the workout, Sara can switch the day to rest, which flips the
nutrition targets to the rest-day macros. Exposed as a chat tool AND a
deliberation action AND a one-tap on the notification.
"""
from datetime import date as _date
from typing import Any, Dict

from app.tools.base import BaseTool, ToolResult


class SetDayTypeTool(BaseTool):
    @property
    def name(self) -> str:
        return "set_day_type"

    @property
    def description(self) -> str:
        return ("Mark a day as a rest day or a training day, overriding the schedule. "
                "Flips the day's nutrition targets to the rest-day / training-day macros. "
                "Use when David skips (or adds) a workout, or asks to switch today to a "
                "rest day. date defaults to today (YYYY-MM-DD).")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "day_type": {"type": "string", "enum": ["rest", "training"]},
                "date": {"type": "string", "description": "YYYY-MM-DD; defaults to today"},
                "note": {"type": "string", "description": "Optional reason"},
            },
            "required": ["day_type"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        day_type = (kwargs.get("day_type") or "").strip()
        note = kwargs.get("note", "")
        try:
            on_date = _date.fromisoformat(kwargs["date"]) if kwargs.get("date") else None
        except ValueError:
            return ToolResult(success=False, message="date must be YYYY-MM-DD.")
        if on_date is None:
            from app.core.timezone import today as _today
            on_date = _today()
        from app.db.session import SessionLocal
        from app.services.training_day import set_day_type
        db = SessionLocal()
        try:
            r = set_day_type(db, user_id, on_date, day_type, note)
        finally:
            db.close()
        if r.get("error"):
            return ToolResult(success=False, message=r["error"])
        verb = "a rest day" if day_type == "rest" else "a training day"
        return ToolResult(success=True, data=r,
                          message=f"Set {r['date']} to {verb} — nutrition targets switched to match.")


DAY_TYPE_TOOLS = [SetDayTypeTool()]
