"""Meeting prep chat tool — "who am I meeting with / prep me for my 2pm"."""

import logging
from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult
from app.core.timezone import now as local_now
from app.services import meeting_research as mr

logger = logging.getLogger(__name__)


def _get_db():
    from app.db.session import get_db
    return next(get_db())


class MeetingPrepTool(BaseTool):
    """Prep David for an upcoming business meeting/demo."""

    @property
    def name(self) -> str:
        return "meeting_prep"

    @property
    def description(self) -> str:
        return (
            "Prep David for an upcoming meeting or demo. Use when he asks 'who am I "
            "meeting with', 'prep me for my next meeting', 'what do I need to know "
            "before my 2pm', or about an upcoming call with a company or person. "
            "Identifies the counterparty company (from the event title and matched "
            "meeting-invite emails), surfaces the last email thread and what we "
            "already know. Does NOT start background research. Covers only David's "
            "own business meetings, never gym, family, or personal events."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional words matching the specific event title (e.g. 'IRMI', 'Amplo'). Omit for the next upcoming business meeting.",
                },
                "within_days": {
                    "type": "integer",
                    "description": "How many days ahead to search (default 14).",
                    "default": 14,
                },
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        within_days = int(kwargs.get("within_days") or 14)

        db = _get_db()
        try:
            now = local_now().replace(tzinfo=None)
            rows = db.execute(
                text("""
                    SELECT id, title, description, location, start_time, ios_calendar_name
                    FROM calendar_event
                    WHERE user_id = :uid
                      AND start_time > :now
                      AND start_time < :end
                    ORDER BY start_time ASC
                    LIMIT 50
                """),
                {"uid": user_id, "now": now, "end": now + timedelta(days=within_days)},
            ).mappings().all()

            if not rows:
                return ToolResult(
                    success=True,
                    message=f"No upcoming events in the next {within_days} days.",
                )

            # Pick the event: explicit query match first, else the next event
            # that reads as a business meeting, else just the next event.
            chosen = None
            if query:
                qtokens = mr._tokens(query)
                for r in rows:
                    if qtokens & mr._tokens(r["title"]):
                        chosen = dict(r)
                        break
            if not chosen:
                for r in rows:
                    related = mr.find_related_invite(db, user_id, r["title"], r["start_time"])
                    if mr.is_business_meeting(r["title"], r["ios_calendar_name"], related):
                        chosen = dict(r)
                        break
            if not chosen:
                chosen = dict(rows[0])

            prep = mr.build_prep(db, user_id, chosen)
            message = mr.format_prep(prep)

            return ToolResult(success=True, data=prep, message=message)
        except Exception as e:
            logger.error("meeting_prep failed: %s", e, exc_info=True)
            return ToolResult(success=False, message=f"Couldn't build meeting prep: {e}")
        finally:
            db.close()
